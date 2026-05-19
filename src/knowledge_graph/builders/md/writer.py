"""MD builder writer + facade-shaped ``extract``.

Mirrors :mod:`knowledge_graph.builders.sv.writer` in surface area but is
much smaller: one node table (``:Node``, shared with SV), one rel table
(``PARENT_OF``), one ``IN_ORIGIN`` per node. No semantic-promotion pass,
no placeholder synthesis, no per-edge payload extractors.

The ``extract`` signature matches the SV builder's so the facade's
generic dispatcher can call either uniformly. Stats are the shared
:class:`knowledge_graph.builders.sv.writer.ExtractStats` /
:class:`WriteStats` types — reusing them keeps the facade's "result tuple
ending in ExtractStats" contract intact without a parallel hierarchy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge_graph.builders.md.lift import MdNode, lift_markdown
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


def _node_id(origin_id: str, kind: str, start: int, end: int) -> str:
    """Deterministic id from origin + kind + span — stable across runs.

    Two distinct tokens never collide because two MdNodes can't share the
    same (kind, start, end) triple (the lifter never emits zero-length
    spans except for MdDocument, which is unique-per-origin).
    """
    h = hashlib.sha256()
    h.update(origin_id.encode("ascii"))
    h.update(b"\x00")
    h.update(kind.encode("ascii"))
    h.update(b"\x00")
    h.update(str(start).encode("ascii"))
    h.update(b":")
    h.update(str(end).encode("ascii"))
    return "md:" + h.hexdigest()[:24]


def _serialize_payload(node: MdNode) -> str:
    return json.dumps(
        {
            "type": node.kind,
            "payload": dict(node.payload),
            "text": node.text,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def write_md_graph(
    store: Any,
    md_nodes: list[MdNode],
    *,
    content: bytes,
    origin: OriginRef,
    source: str = "md",
    corpus: str,
) -> WriteStats:
    """Write a single file's MdNodes to the store.

    Categorisation: every MD node is ``structural`` for now — the v1
    surface has no semantic promotion. Connectors are the *only* writers
    of cross-builder semantics.
    """
    stats = WriteStats()
    conn = store.conn
    id_by_index: dict[int, str] = {}

    for idx, mn in enumerate(md_nodes):
        nid = _node_id(origin.id, mn.kind, mn.start, mn.end)
        id_by_index[idx] = nid
        sl, sc = _line_col(content, mn.start)
        el, ec = _line_col(content, mn.end)
        # Name: for MdDocument use the uri stem; for headings/inline-code
        # use the lifted text so connectors can match on n.name.
        if mn.kind == "MdDocument":
            name = Path(origin.uri).name
        else:
            name = mn.text
        conn.execute(
            _NODE_MERGE_CYPHER,
            {
                "id": nid,
                "kind": mn.kind,
                "category": "structural",
                "name": name,
                "source": source,
                "corpus": corpus,
                "origin_id": origin.id,
                "start_offset": mn.start,
                "end_offset": mn.end,
                "start_line": sl,
                "end_line": el,
                "start_col": sc,
                "end_col": ec,
                "payload": _serialize_payload(mn),
            },
        )
        stats.nodes_written += 1
        conn.execute(_IN_ORIGIN_MERGE, {"nid": nid, "oid": origin.id})
        stats.in_origin_written += 1

    # PARENT_OF edges from each non-root to its parent index.
    ordinal_by_parent: dict[int, int] = {}
    for idx, mn in enumerate(md_nodes):
        if mn.parent_idx is None:
            continue
        ord_ = ordinal_by_parent.get(mn.parent_idx, 0)
        ordinal_by_parent[mn.parent_idx] = ord_ + 1
        conn.execute(
            _PARENT_OF_MERGE,
            {
                "src": id_by_index[mn.parent_idx],
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
    md_paths: list[Path] | list[str],
    *,
    source: str = "md",
    corpus: str,
    lang: str = "markdown",
    prune: bool = False,
    gc: bool = False,
) -> tuple[None, dict[str, OriginRef], ExtractStats]:
    """Incremental MD extract.

    Same replacement-merge semantics as :func:`builders.sv.writer.extract`:

    * unchanged sha256 → skip;
    * changed sha256 → delete previous Origin subtree, re-write;
    * ``prune=True`` (implied by ``gc=True``) → sweep stale origins for
      ``(source, corpus)``;
    * ``gc=True`` → also run :meth:`KGStore.prune_orphaned_origins` for
      ``(source, corpus)`` after writes.
    """
    paths = [Path(p) for p in md_paths]

    stats_e = ExtractStats(write_stats=None)
    new_uris: set[str] = set()
    touched: list[tuple[Path, OriginRef]] = []
    origins_by_uri: dict[str, OriginRef] = {}

    for p in paths:
        from knowledge_graph.shared.ids import sha256_bytes

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
            store.prune_orphaned_origins(source=source, corpus=corpus)
        return None, origins_by_uri, stats_e

    # Combine per-file WriteStats into one aggregate.
    agg = WriteStats()
    for path, origin in touched:
        content = path.read_bytes()
        md_nodes = lift_markdown(content)
        s = write_md_graph(
            store,
            md_nodes,
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
        store.prune_orphaned_origins(source=source, corpus=corpus)
    return None, origins_by_uri, stats_e


__all__ = ["extract", "write_md_graph"]
