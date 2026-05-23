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

import hashlib
import json
from pathlib import Path
from typing import Any

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
    """
    stats = WriteStats()
    conn = store.conn
    id_by_index: dict[int, str] = {}

    for idx, pn in enumerate(py_nodes):
        # For the module node, use the file basename as the name so
        # downstream connectors can match against ``import simple_module``.
        if pn.kind == "PyModule":
            name = Path(origin.uri).stem
        else:
            name = pn.name
        nid = _node_id(origin.id, pn.kind, pn.start, pn.end, name)
        id_by_index[idx] = nid
        sl, sc = _line_col(content, pn.start)
        el, ec = _line_col(content, pn.end)
        conn.execute(
            _NODE_MERGE_CYPHER,
            {
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
            },
        )
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
