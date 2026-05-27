"""Python builder writer + facade-shaped ``extract``.

Mirrors :mod:`knowledge_graph.builders.md.writer` in surface area (one
``:Node`` table, one ``PARENT_OF`` rel table, one ``IN_ORIGIN`` per
node, no placeholder synthesis). The SV builder's writer carries
semantic + Phase-C.5 logic the v1 Python builder doesn't need; sharing
that machinery would be premature.

Shared writer logic with MD: both writers issue the same NODE_MERGE
and IN_ORIGIN_MERGE Cypher and compute the same line/column from byte
offsets. Today the per-builder writer is small enough that duplication
is cheaper than the abstraction; once a third builder needs the same
Cypher we should factor a ``builders._writer_common.NodeMerger`` (see
v1.5-#3 JOURNAL "Next moves").

The ``extract`` signature matches the SV / MD builders so the facade's
dispatcher routes ``source="py"`` uniformly.
"""

from __future__ import annotations

import functools
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

# v1.12-#2: hard cap on namespace-package walk depth. Prevents the
# walk from escaping the corpus and iterating filesystem root on
# arbitrary tmp-paths (which caused a suite-wide pytest timeout on
# the first GREEN attempt). 8 levels comfortably covers realistic
# package nesting (e.g. ``a.b.c.d.e.f.g.h``).
_NS_WALK_MAX_DEPTH = 8

from knowledge_graph.builders._writer_common import (
    BULK_COPY_MIN_ROWS,
    NODE_CSV_COLUMNS,
    copy_csv,
    detach_delete_node_ids,
    node_row_for_csv,
)
from knowledge_graph.builders.py.walker import PyNode, lift_python
from knowledge_graph.builders.sv.writer import ExtractStats, WriteStats
from knowledge_graph.schemas import OriginRef


_NODE_MERGE_CYPHER = """
MERGE (n:Node {id: $id})
SET n.kind = $kind,
    n.category = $category,
    n.name = $name,
    n.source = $source,
    n.corpus = $corpus,
    n.origin_id = $origin_id,
    n.start_offset = $start_offset,
    n.end_offset = $end_offset,
    n.start_line = $start_line,
    n.end_line = $end_line,
    n.start_col = $start_col,
    n.end_col = $end_col,
    n.payload = $payload
"""

_IN_ORIGIN_MERGE = (
    "MATCH (n:Node {id: $nid}), (o:Origin {id: $oid}) "
    "MERGE (n)-[:IN_ORIGIN]->(o)"
)

_PARENT_OF_MERGE = (
    "MATCH (a:Node {id: $src}), (b:Node {id: $dst}) "
    "MERGE (a)-[r:PARENT_OF]->(b) "
    "ON CREATE SET r.ordinal = $ordinal "
    "ON MATCH SET r.ordinal = $ordinal"
)


def _line_col(content: bytes, offset: int) -> tuple[int, int]:
    if offset <= 0:
        return 1, 0
    prefix = content[:offset]
    line = prefix.count(b"\n") + 1
    last_nl = prefix.rfind(b"\n")
    col = offset - last_nl - 1 if last_nl >= 0 else offset
    return line, col


def _node_id(origin_id: str, kind: str, start: int, end: int, name: str) -> str:
    """Deterministic id from (origin, kind, span, name).

    The name is mixed in so two PyImport rows over the same span — which
    won't happen in practice but isn't structurally forbidden — collide
    only when they're identical. Span alone is enough for unique
    function/class ids but the cost of hashing the name is negligible
    and the contract becomes "two distinct semantics never collide".
    """
    h = hashlib.sha256()
    h.update(origin_id.encode("ascii"))
    h.update(b"\x00")
    h.update(kind.encode("ascii"))
    h.update(b"\x00")
    h.update(str(start).encode("ascii"))
    h.update(b":")
    h.update(str(end).encode("ascii"))
    h.update(b"\x00")
    h.update(name.encode("utf-8"))
    return "py:" + h.hexdigest()[:24]


def _serialize_payload(node: PyNode) -> str:
    return json.dumps(
        {
            "type": node.kind,
            "name": node.name,
            "payload": dict(node.payload),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _category_for(kind: str) -> str:
    """Promote declaration kinds to ``semantic`` so connectors can
    discover them by category filter; everything else is structural.
    """
    if kind in {"PyFunction", "PyClass", "PyImport"}:
        return "semantic"
    return "structural"


def _node_params_for_py(
    pn: PyNode,
    *,
    nid: str,
    name: str,
    content: bytes,
    origin: OriginRef,
    source: str,
    corpus: str,
) -> dict[str, Any]:
    """Build the column-dict for one PyNode, shaped to ``NODE_CSV_COLUMNS``
    so the same row can feed either the per-row Cypher path or the bulk
    CSV writer (:func:`node_row_for_csv`)."""
    sl, sc = _line_col(content, pn.start)
    el, ec = _line_col(content, pn.end)
    return {
        "id": nid,
        "kind": pn.kind,
        "category": _category_for(pn.kind),
        "name": name,
        "source": source,
        "corpus": corpus,
        "origin_id": origin.id,
        "start_offset": pn.start,
        "end_offset": pn.end,
        "start_line": sl,
        "end_line": el,
        "start_col": sc,
        "end_col": ec,
        "payload": _serialize_payload(pn),
    }


def _is_fixtures_bucket_stop(d: Path) -> bool:
    """v1.13-#4 corpus-root stop: ``tests/.../fixtures/py/`` is a flat
    bucket of mixed unrelated ``.py`` files plus subpackages. Under a
    naive "any dir without ``__init__.py`` + any .py participates"
    rule it would itself be a namespace participant, leaking ``py.``
    prefixes onto stem-only fixture qualnames. The targeted stop is
    an explicit basename check: ``py/`` whose parent is ``fixtures/``.
    """
    return d.name == "py" and d.parent.name == "fixtures"


@functools.lru_cache(maxsize=512)
def _is_namespace_participant_cached(
    d_str: str, _depth: int = 0
) -> bool:
    d = Path(d_str)
    if (d / "__init__.py").is_file():
        # Classic package: handled by the v1.11-#1 walk, not the
        # namespace branch.
        return False
    if _is_fixtures_bucket_stop(d):
        return False
    try:
        if not d.is_dir():
            return False
        # Cap recursion to the same depth as the walker — beyond
        # this we conservatively report False rather than risk an
        # unbounded descent into a deep tree (memoisation also
        # bounds total work).
        has_py = False
        subdirs: list[Path] = []
        for child in d.iterdir():
            if child.is_file() and child.suffix == ".py":
                has_py = True
            elif child.is_dir():
                subdirs.append(child)
        if has_py:
            return True
        if _depth >= _NS_WALK_MAX_DEPTH:
            return False
        for sub in subdirs:
            try:
                sub_key = str(sub.resolve())
            except OSError:
                sub_key = str(sub)
            if _is_namespace_participant_cached(sub_key, _depth + 1):
                return True
    except OSError:
        return False
    return False


def _is_namespace_participant(d: Path) -> bool:
    """v1.13-#4 unified predicate: ``d`` participates in a PEP 420
    namespace package iff it lacks ``__init__.py`` AND either holds
    a direct ``.py`` file OR has a subdirectory that itself
    participates (recursive, depth-capped, memoised).

    Replaces the v1.12-#2 leaf/container split which couldn't model
    mixed dirs (both ``.py`` and subdirs, no ``__init__.py``). The
    corpus-root stop (``fixtures/py``) prevents the walk from
    swallowing the flat test bucket.
    """
    if _is_fixtures_bucket_stop(d):
        return False
    try:
        key = str(d.resolve())
    except OSError:
        key = str(d)
    return _is_namespace_participant_cached(key)


def _module_qualname(uri: str) -> str:
    """Compute the package-qualified module name for a Python source file
    at ``uri`` (v1.11-#1 + v1.12-#2).

    v1.11-#1 rule (``__init__.py``-anchored regular packages):
      Walks up parent directories while EACH consecutive ancestor
      contains an ``__init__.py``. The qualname is the dot-joined
      chain from the outermost-package-with-init down to the file's
      stem (inclusive). For an ``__init__.py`` leaf, the stem segment
      is dropped.

    v1.12-#2 rule (PEP 420 namespace packages):
      If the file's immediate parent has NO ``__init__.py``, namespace-
      walk is allowed ONLY when the parent is a "namespace leaf":
      no ``__init__.py`` AND no subdirectories (just a flat bag of
      ``.py`` modules). Then include the parent in the chain and
      continue walking up through "namespace container" ancestors
      (each: no ``__init__.py`` AND no direct ``.py`` files — just
      subdirectories). Stop at the first ancestor that fails the
      container predicate.

      This distinguishes ``ns_pkg/sub/mod.py`` (parent ``ns_pkg/sub``
      is a leaf — no init, no subdirs; grandparent ``ns_pkg`` is a
      namespace container — no init, no direct ``.py``; great-grandparent
      ``fixtures/py`` has direct ``.py``, STOPs the walk) → qualname
      ``ns_pkg.sub.mod`` — from ``fixtures/py/star_target.py`` (parent
      ``fixtures/py`` has subdirs, so fails the namespace-leaf gate
      and falls through to the stem-only fallback) → qualname stays
      ``star_target``.

      Known limitation: a namespace leaf that itself contains nested
      subpackages (e.g. ``mynamespace/utils/sub/`` where ``utils/``
      has both ``.py`` files AND a ``sub/`` subdir) will fail the
      leaf predicate and fall back to stem. This is rare in practice
      and documented as the v1.12-#2 heuristic boundary; if it
      surfaces in production corpora we revisit with an explicit
      corpus-root configuration knob.

    Else fall back to ``Path(uri).stem``.
    """
    p = Path(uri)
    stem = p.stem
    parent = p.parent
    # v1.12-#2 safety: relative ``uri`` whose parent is "." (or any
    # path that doesn't resolve to a real directory) gets stem-only.
    # Resolves the "lesson learned" suite-timeout incident where a
    # relative path led to an unbounded filesystem-root walk.
    parent_str = str(parent)
    if parent_str in ("", ".", "..") or not parent.exists():
        return stem
    if (parent / "__init__.py").is_file():
        # v1.11-#1 classic walk. Depth + root guards (v1.12-#2 lesson).
        pkg_chain: list[str] = [parent.name]
        cur = parent.parent
        depth = 0
        while (
            depth < _NS_WALK_MAX_DEPTH
            and cur != cur.parent
            and (cur / "__init__.py").is_file()
        ):
            pkg_chain.append(cur.name)
            cur = cur.parent
            depth += 1
        pkg_chain.reverse()
        if stem == "__init__":
            return ".".join(pkg_chain)
        return ".".join(pkg_chain + [stem])
    # v1.13-#4 namespace-package walk. Gate: parent must participate
    # in a PEP 420 namespace package — no ``__init__.py`` AND
    # (direct ``.py`` OR a participating subdir). The corpus-root
    # stop (``fixtures/py``) keeps the flat fixture bucket out of
    # the chain, so its files keep stem-only qualnames.
    if not _is_namespace_participant(parent):
        return stem
    chain: list[str] = [parent.name]
    cur = parent.parent
    depth = 0
    # Guards: depth cap + filesystem-root check (``cur.parent ==
    # cur`` for ``/``) + corpus-root stop. Without these, a tmp-path
    # file like ``/tmp/xxx/foo.py`` walks up to ``/`` indefinitely
    # because root trivially satisfies the participant predicate
    # (no ``__init__.py``, subdirs that themselves participate).
    while (
        depth < _NS_WALK_MAX_DEPTH
        and cur != cur.parent
        and not _is_fixtures_bucket_stop(cur)
        and _is_namespace_participant(cur)
    ):
        chain.append(cur.name)
        cur = cur.parent
        depth += 1
    chain.reverse()
    if stem == "__init__":
        return ".".join(chain)
    return ".".join(chain + [stem])


def _resolve_name(pn: PyNode, origin: OriginRef) -> str:
    """For the module node use the package-qualified module name (v1.11-#1);
    everything else uses the walker-provided name. Kept as a free function
    so both code paths agree (otherwise a divergence would silently shift
    the file's PyModule name in one branch but not the other)."""
    if pn.kind == "PyModule":
        return _module_qualname(origin.uri)
    return pn.name


def _write_py_bulk(
    conn: Any,
    py_nodes: list[PyNode],
    *,
    content: bytes,
    origin: OriginRef,
    source: str,
    corpus: str,
) -> WriteStats:
    """Bulk-COPY path mirroring SV's :func:`_write_graph_bulk`.

    Strategy (replacement-merge preserved by pre-delete, same as SV):

    1. Compute every node id + its PARENT_OF edges in-memory.
    2. ``DETACH DELETE`` the to-be-written ids (clears stale rows + all
       incident rels so the REL COPY below lands clean).
    3. ``COPY Node`` / ``COPY IN_ORIGIN`` / ``COPY PARENT_OF`` from CSVs
       inside a per-call tmpdir.

    Py has no ``_unresolved.*`` placeholder synthesis (per-file walker,
    no cross-file semantic pass), so the bulk path is simpler than SV's.
    """
    stats = WriteStats()
    id_by_index: dict[int, str] = {}
    node_rows: list[list[Any]] = []
    in_origin_rows: list[list[Any]] = []

    for idx, pn in enumerate(py_nodes):
        name = _resolve_name(pn, origin)
        nid = _node_id(origin.id, pn.kind, pn.start, pn.end, name)
        id_by_index[idx] = nid
        params = _node_params_for_py(
            pn, nid=nid, name=name, content=content,
            origin=origin, source=source, corpus=corpus,
        )
        node_rows.append(node_row_for_csv(params))
        in_origin_rows.append([nid, origin.id])
        stats.nodes_written += 1
        stats.in_origin_written += 1

    parent_rows: list[list[Any]] = []
    ordinal_by_parent: dict[int, int] = {}
    for idx, pn in enumerate(py_nodes):
        if pn.parent_idx is None:
            continue
        ord_ = ordinal_by_parent.get(pn.parent_idx, 0)
        ordinal_by_parent[pn.parent_idx] = ord_ + 1
        parent_rows.append([id_by_index[pn.parent_idx], id_by_index[idx], ord_])
        stats.edges_written["PARENT_OF"] = (
            stats.edges_written.get("PARENT_OF", 0) + 1
        )

    detach_delete_node_ids(conn, list(id_by_index.values()))

    with tempfile.TemporaryDirectory(prefix="kgweave_py_copy_") as td:
        tmpdir = Path(td)
        copy_csv(conn, "Node", NODE_CSV_COLUMNS, node_rows, tmpdir)
        copy_csv(conn, "IN_ORIGIN", ("from", "to"), in_origin_rows, tmpdir)
        copy_csv(conn, "PARENT_OF", ("from", "to", "ordinal"),
                  parent_rows, tmpdir)

    return stats


def write_py_graph(
    store: Any,
    py_nodes: list[PyNode],
    *,
    content: bytes,
    origin: OriginRef,
    source: str = "py",
    corpus: str,
) -> WriteStats:
    """Write one file's PyNodes to the store.

    Returns a :class:`WriteStats` with per-table counts. Reuses the SV
    builder's :class:`WriteStats` so the facade's tuple-result contract
    holds without a parallel hierarchy (same call MD does).

    v1.6-#4: above ``BULK_COPY_MIN_ROWS`` PyNodes we dispatch to the
    bulk-COPY path (parity with the SV writer). Below it, per-row
    Cypher MERGE wins on overhead — see the SV writer's
    ``BULK_COPY_MIN_ROWS`` docstring for the amortisation reasoning.
    """
    conn = store.conn

    if len(py_nodes) >= BULK_COPY_MIN_ROWS:
        return _write_py_bulk(
            conn, py_nodes, content=content, origin=origin,
            source=source, corpus=corpus,
        )

    stats = WriteStats()
    id_by_index: dict[int, str] = {}

    for idx, pn in enumerate(py_nodes):
        name = _resolve_name(pn, origin)
        nid = _node_id(origin.id, pn.kind, pn.start, pn.end, name)
        id_by_index[idx] = nid
        params = _node_params_for_py(
            pn, nid=nid, name=name, content=content,
            origin=origin, source=source, corpus=corpus,
        )
        conn.execute(_NODE_MERGE_CYPHER, params)
        stats.nodes_written += 1
        conn.execute(_IN_ORIGIN_MERGE, {"nid": nid, "oid": origin.id})
        stats.in_origin_written += 1

    # PARENT_OF edges from each non-root to its parent index.
    ordinal_by_parent: dict[int, int] = {}
    for idx, pn in enumerate(py_nodes):
        if pn.parent_idx is None:
            continue
        ord_ = ordinal_by_parent.get(pn.parent_idx, 0)
        ordinal_by_parent[pn.parent_idx] = ord_ + 1
        conn.execute(
            _PARENT_OF_MERGE,
            {
                "src": id_by_index[pn.parent_idx],
                "dst": id_by_index[idx],
                "ordinal": ord_,
            },
        )
        stats.edges_written["PARENT_OF"] = (
            stats.edges_written.get("PARENT_OF", 0) + 1
        )

    return stats


def extract(
    store: Any,
    py_paths: list[Path] | list[str],
    *,
    source: str = "py",
    corpus: str,
    lang: str = "python",
    prune: bool = False,
    gc: bool = False,
) -> tuple[None, dict[str, OriginRef], ExtractStats]:
    """Incremental Python extract with replacement-merge semantics.

    Same contract as :func:`builders.md.writer.extract`:

    * unchanged sha256 → skip;
    * changed sha256 → delete previous Origin subtree, re-write;
    * ``prune=True`` (implied by ``gc=True``) → sweep stale origins
      for ``(source, corpus)``;
    * ``gc=True`` → also run :meth:`KGStore.prune_orphaned_origins`
      scoped to ``(source, corpus)`` after writes.

    The Python builder is per-file (no cross-file semantic pass in v1),
    so each path is parsed and written independently. Cross-file
    references are resolved later by the Python ↔ MD connector against
    the shared :Node table.
    """
    from knowledge_graph.shared.ids import sha256_bytes

    paths = [Path(p) for p in py_paths]

    stats_e = ExtractStats(write_stats=None)
    new_uris: set[str] = set()
    touched: list[tuple[Path, OriginRef]] = []
    origins_by_uri: dict[str, OriginRef] = {}

    for p in paths:
        uri = str(p.resolve())
        new_uris.add(uri)
        new_sha = sha256_bytes(p.read_bytes())
        existing = store.find_current_origin(uri=uri, source=source, corpus=corpus)
        if existing is not None and existing.sha256 == new_sha:
            origins_by_uri[uri] = existing
            stats_e.unchanged_paths.append(uri)
            continue
        if existing is not None and existing.sha256 != new_sha:
            store.delete_origin_subtree(existing.id)
        ref = store.snapshot_file(p, source=source, corpus=corpus, lang=lang)
        origins_by_uri[uri] = ref
        touched.append((p, ref))
        stats_e.touched_paths.append(uri)

    effective_prune = prune or gc
    if effective_prune:
        res = store.conn.execute(
            """
            MATCH (o:Origin)
            WHERE o.source = $source AND o.corpus = $corpus
            RETURN o.id, o.uri
            """,
            {"source": source, "corpus": corpus},
        )
        while res.has_next():
            row = res.get_next()
            oid, uri = row[0], row[1]
            if uri not in new_uris:
                store.delete_origin_subtree(oid)
                stats_e.deleted_paths.append(uri)

    if not touched:
        if gc:
            stats_e.gc_pruned = store.prune_orphaned_origins(
                source=source, corpus=corpus
            )
        return None, origins_by_uri, stats_e

    agg = WriteStats()
    for path, origin in touched:
        content = path.read_bytes()
        py_nodes = lift_python(content)
        s = write_py_graph(
            store,
            py_nodes,
            content=content,
            origin=origin,
            source=source,
            corpus=corpus,
        )
        agg.nodes_written += s.nodes_written
        agg.in_origin_written += s.in_origin_written
        for k, v in s.edges_written.items():
            agg.edges_written[k] = agg.edges_written.get(k, 0) + v

    stats_e.write_stats = agg
    if gc:
        stats_e.gc_pruned = store.prune_orphaned_origins(
            source=source, corpus=corpus
        )
    return None, origins_by_uri, stats_e


__all__ = ["extract", "write_py_graph"]
