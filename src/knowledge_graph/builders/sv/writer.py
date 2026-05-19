"""Graph-dict → Kuzu writer for the SV builder.

The :func:`write_graph` function takes the in-memory dict produced by
:func:`knowledge_graph.builders.sv.build.build_kg` and materializes it in a
Kuzu store opened via :class:`knowledge_graph.store.KGStore`.

Two-layer category rule (per Phase C plan):

* ``semantic``   — ``node.get("queryable")`` is True.
* ``token``      — ``node.get("is_token")`` is True.
* ``structural`` — anything else.

Edge mapping mirrors the table set in ``store/schema.py``. Every node also
gets an ``IN_ORIGIN`` edge to its origin row.

Idempotency: every write uses ``MERGE`` on the primary key — re-running the
writer against an unchanged graph produces zero row deltas.

Origin mapping: SV node ids are namespaced by file-path stem (see
``build.py``). The writer requires a ``origins: dict[str, OriginRef]`` map
keyed by *id prefix* (the part before the first ``:`` in the node id) so it
can attach each node to the correct ``:Origin``. :func:`build_and_store`
constructs this map for the standard multi-file path.

Edges whose endpoints reference unknown node ids are skipped with a
diagnostic counter in the returned :class:`WriteStats`; node-only writes are
unaffected. This matches the plan's "fail loudly or buffer-and-resolve"
contract — we choose *skip with stats* since Kuzu rel tables would otherwise
raise on the missing FK and abort the whole batch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from knowledge_graph.schemas import OriginRef


# Map from graph-dict edge ``type`` → (rel table name, payload-extractor).
# The extractor returns the dict of REL-table column values that aren't
# (src, dst). ``None`` means no extra columns.
def _edge_payload_index(e: dict[str, Any]) -> dict[str, Any]:
    return {"ordinal": int(e.get("payload", {}).get("index", 0))}


def _edge_payload_sensitive(e: dict[str, Any]) -> dict[str, Any]:
    return {"edge": str(e.get("payload", {}).get("edge", ""))}


def _edge_payload_connects(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "instance": str(p.get("instance", "") or ""),
        "port": str(p.get("port", "") or ""),
    }


def _edge_payload_param_override(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "name": str(p.get("name", "") or ""),
        "value": str(p.get("value", "") or ""),
    }


def _edge_payload_enum_value(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "name": str(p.get("name", "") or ""),
        "typedef": str(p.get("typedef", "") or ""),
    }


EDGE_TABLE_MAP: dict[str, tuple[str, Any]] = {
    "child":           ("PARENT_OF",      _edge_payload_index),
    "drives":          ("DRIVES",         None),
    "reads":           ("READS",          None),
    "sensitive_to":    ("SENSITIVE_TO",   _edge_payload_sensitive),
    "instantiates":    ("INSTANTIATES",   None),
    "of_module":       ("OF_MODULE",      None),
    "connects":        ("CONNECTS",       _edge_payload_connects),
    "param_override":  ("PARAM_OVERRIDE", _edge_payload_param_override),
    "has_port":        ("HAS_PORT",       None),
    "has_param":       ("HAS_PARAM",      None),
    "has_net":         ("HAS_NET",        None),
    "has_typedef":     ("HAS_TYPEDEF",    None),
    "has_enum_value":  ("HAS_ENUM_VALUE", _edge_payload_enum_value),
    "has_modport":     ("HAS_MODPORT",    None),
    "has_function":    ("HAS_FUNCTION",   None),
    "has_generate":    ("HAS_GENERATE",   None),
    "contains_block":  ("CONTAINS_BLOCK", None),
    "calls":           ("CALLS",          None),
}


@dataclass
class WriteStats:
    """Diagnostic counters returned by :func:`write_graph`."""

    nodes_written: int = 0
    in_origin_written: int = 0
    edges_written: dict[str, int] = field(default_factory=dict)
    edges_skipped_missing_endpoint: int = 0
    edges_skipped_unknown_type: dict[str, int] = field(default_factory=dict)


def _category_for(node: dict[str, Any]) -> str:
    if node.get("queryable"):
        return "semantic"
    if node.get("is_token"):
        return "token"
    return "structural"


def _prefix_of(node_id: str) -> str:
    """Return the id-prefix used by :func:`build_kg` for namespacing.

    Node ids look like ``<prefix>:n0001.<Class>``; the prefix is the file
    stem (with a numeric suffix for stem collisions). For ungrafted ids
    (no colon) the empty string is returned — callers must handle that
    case if they care.
    """
    idx = node_id.find(":")
    return node_id[:idx] if idx >= 0 else ""


def _serialize_payload(node: dict[str, Any]) -> str:
    """Lossless JSON payload — everything not promoted to a column.

    Includes the structural ``type``, the original ``payload`` dict, plus
    ``semantic`` and ``queryable`` flags when present. The ``span``, ``id``,
    ``kind``, ``is_token`` keys are intentionally excluded — they're either
    promoted to columns or derivable.
    """
    out: dict[str, Any] = {
        "type": node.get("type"),
        "payload": node.get("payload", {}),
    }
    if "semantic" in node:
        out["semantic"] = node["semantic"]
    if node.get("queryable"):
        out["queryable"] = True
    return json.dumps(out, ensure_ascii=False, sort_keys=True, default=str)


def _node_params(
    node: dict[str, Any],
    *,
    source: str,
    corpus: str,
    origin_id: str,
) -> dict[str, Any]:
    span = node.get("span") or {}
    name = None
    sem = node.get("semantic")
    if isinstance(sem, dict):
        n = sem.get("name")
        if isinstance(n, str):
            name = n
    return {
        "id": node["id"],
        "kind": str(node.get("kind", "")),
        "category": _category_for(node),
        "name": name,
        "source": source,
        "corpus": corpus,
        "origin_id": origin_id,
        "start_offset": int(span.get("start_offset", -1)) if span else -1,
        "end_offset": int(span.get("end_offset", -1)) if span else -1,
        "start_line": int(span.get("start_line", 0) or 0) if span else 0,
        "end_line": int(span.get("end_line", 0) or 0) if span else 0,
        "start_col": int(span.get("start_col", 0) or 0) if span else 0,
        "end_col": int(span.get("end_col", 0) or 0) if span else 0,
        "payload": _serialize_payload(node),
    }


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


_IN_ORIGIN_MERGE_CYPHER = """
MATCH (n:Node {id: $nid}), (o:Origin {id: $oid})
MERGE (n)-[:IN_ORIGIN]->(o)
"""


def _rel_cypher(table: str, extra_cols: Iterable[str]) -> str:
    sets = ", ".join(f"r.{c} = ${c}" for c in extra_cols)
    set_clause = f"\nON CREATE SET {sets}\nON MATCH SET {sets}" if sets else ""
    return (
        f"MATCH (a:Node {{id: $src}}), (b:Node {{id: $dst}})\n"
        f"MERGE (a)-[r:{table}]->(b)"
        f"{set_clause}"
    )


def _resolve_origins_for_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    origins: dict[str, OriginRef],
    order: list[str],
) -> dict[str, OriginRef]:
    """Map every node id → OriginRef.

    Strategy:

    1. If the node's id-prefix is in ``origins``, use that.
    2. Otherwise propagate from any inbound edge (typically a ``has_*`` edge
       from a structural parent whose prefix *is* mapped). Iterate to a
       fixed point so chains of synthetic nodes resolve too.
    3. Any still-unresolved node falls back to the origin of the first root
       in ``graph["order"]`` — guarantees ``IN_ORIGIN`` is never null.

    The brief flags this case explicitly: semantic blobs like
    ``checker_data:c_mutex.r_dir`` are not lifted from any single file's
    parse but are owned by a structural declaration in one file.
    """
    by_id_prefix = {n["id"]: _prefix_of(n["id"]) for n in nodes}
    resolved: dict[str, OriginRef] = {}
    unresolved: list[str] = []
    for nid, prefix in by_id_prefix.items():
        ref = origins.get(prefix)
        if ref is not None:
            resolved[nid] = ref
        else:
            unresolved.append(nid)

    if unresolved:
        # Build reverse adjacency once: dst -> list of srcs.
        in_edges: dict[str, list[str]] = {}
        for e in edges:
            in_edges.setdefault(e["dst"], []).append(e["src"])

        progress = True
        while progress and unresolved:
            progress = False
            still: list[str] = []
            for nid in unresolved:
                ref = None
                for src in in_edges.get(nid, []):
                    if src in resolved:
                        ref = resolved[src]
                        break
                if ref is not None:
                    resolved[nid] = ref
                    progress = True
                else:
                    still.append(nid)
            unresolved = still

    if unresolved:
        # Final fallback: first file's origin.
        fallback: OriginRef | None = None
        for root in order:
            ref = origins.get(_prefix_of(root))
            if ref is not None:
                fallback = ref
                break
        if fallback is None and origins:
            fallback = next(iter(origins.values()))
        if fallback is None:
            raise KeyError("no origins provided and no fallback available")
        for nid in unresolved:
            resolved[nid] = fallback

    return resolved


def write_graph(
    store: Any,
    graph: dict[str, Any],
    *,
    source: str = "sv",
    corpus: str,
    origins: dict[str, OriginRef],
) -> WriteStats:
    """Materialize ``graph`` into ``store`` (a :class:`KGStore`).

    ``origins`` maps the SV id-prefix (file stem with optional collision
    suffix) to the :class:`OriginRef` for that file. Nodes whose prefix is
    not in the map are routed via their structural parent (see
    :func:`_resolve_origins_for_nodes`).

    Returns a :class:`WriteStats` with per-table counts.
    """
    stats = WriteStats()
    conn = store.conn

    nodes: list[dict[str, Any]] = graph.get("nodes", [])
    edges: list[dict[str, Any]] = graph.get("edges", [])
    order: list[str] = graph.get("order", []) or []

    node_origin = _resolve_origins_for_nodes(nodes, edges, origins, order)
    known_ids: set[str] = set()

    # --- nodes -------------------------------------------------------------
    for node in nodes:
        nid = node["id"]
        origin = node_origin[nid]
        params = _node_params(node, source=source, corpus=corpus, origin_id=origin.id)
        conn.execute(_NODE_MERGE_CYPHER, params)
        stats.nodes_written += 1
        known_ids.add(nid)

    # --- IN_ORIGIN edges ---------------------------------------------------
    for node in nodes:
        nid = node["id"]
        origin = node_origin[nid]
        conn.execute(_IN_ORIGIN_MERGE_CYPHER, {"nid": nid, "oid": origin.id})
        stats.in_origin_written += 1

    # --- typed edges -------------------------------------------------------
    for edge in edges:
        etype = edge.get("type")
        mapping = EDGE_TABLE_MAP.get(etype)
        if mapping is None:
            stats.edges_skipped_unknown_type[etype] = (
                stats.edges_skipped_unknown_type.get(etype, 0) + 1
            )
            continue
        table, extractor = mapping
        src = edge.get("src")
        dst = edge.get("dst")
        if src not in known_ids or dst not in known_ids:
            stats.edges_skipped_missing_endpoint += 1
            continue
        params: dict[str, Any] = {"src": src, "dst": dst}
        extra_cols: tuple[str, ...] = ()
        if extractor is not None:
            extra = extractor(edge)
            params.update(extra)
            extra_cols = tuple(extra.keys())
        conn.execute(_rel_cypher(table, extra_cols), params)
        stats.edges_written[table] = stats.edges_written.get(table, 0) + 1

    return stats


# --------------------------------------------------------------------------
# Full-pipeline convenience entry point used by Phase F's facade.
# --------------------------------------------------------------------------


def _prefix_for_path(path: Path, seen: dict[str, int]) -> str:
    """Reproduce :func:`build_kg`'s stem-collision prefix scheme."""
    stem = path.stem or f"file{len(seen)}"
    n = seen.get(stem, 0)
    seen[stem] = n + 1
    return stem if n == 0 else f"{stem}{n}"


def build_and_store(
    store: Any,
    sv_paths: list[Path] | list[str],
    *,
    source: str = "sv",
    corpus: str,
    lang: str = "systemverilog",
) -> tuple[dict[str, Any], dict[str, OriginRef], WriteStats]:
    """Snapshot → build_kg → write_graph in one shot.

    Returns ``(graph, origins_by_prefix, stats)`` so callers can introspect
    the in-memory build and the persisted-row counts.
    """
    from .build import build_kg  # avoid circular import at module load

    paths = [Path(p) for p in sv_paths]

    # 1. Snapshot each file (idempotent on (uri, sha256)).
    seen: dict[str, int] = {}
    origins_by_prefix: dict[str, OriginRef] = {}
    for p in paths:
        prefix = _prefix_for_path(p, seen)
        ref = store.snapshot_file(p, source=source, corpus=corpus, lang=lang)
        origins_by_prefix[prefix] = ref

    # 2. Build the in-memory graph (uses the same stem-prefix scheme).
    graph, _trees, _comp = build_kg(paths)

    # 3. Materialize.
    stats = write_graph(
        store, graph, source=source, corpus=corpus, origins=origins_by_prefix
    )
    return graph, origins_by_prefix, stats


# --------------------------------------------------------------------------
# Phase E: incremental extract with scoped replacement.
# --------------------------------------------------------------------------


@dataclass
class ExtractStats:
    """Diagnostic summary of an :func:`extract` call.

    ``touched_paths`` = files whose content changed (or are new) — their
    origin subtree was deleted (if present) and re-written.
    ``unchanged_paths`` = files whose sha256 already matched a live origin
    — skipped entirely on the write side.
    ``deleted_paths`` = files swept under ``prune=True`` (origin existed for
    ``(source, corpus)`` but path was not in this call).
    """

    touched_paths: list[str] = field(default_factory=list)
    unchanged_paths: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)
    write_stats: WriteStats | None = None


def _sha_of(path: Path) -> str:
    from knowledge_graph.shared.ids import sha256_bytes
    return sha256_bytes(path.read_bytes())


def extract(
    store: Any,
    sv_paths: list[Path] | list[str],
    *,
    source: str = "sv",
    corpus: str,
    lang: str = "systemverilog",
    prune: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, OriginRef], ExtractStats]:
    """Incremental SV extract with replacement semantics.

    For each input path:

    * If a current ``:Origin`` exists for ``(uri, source, corpus)`` with a
      DIFFERENT sha256 — that origin's subtree (origin + nodes + all rels
      touching those nodes) is **deleted**; the new content is snapshotted.
    * If no current origin exists — the file is snapshotted fresh.
    * If a current origin exists with a MATCHING sha — the file is marked
      unchanged and skipped on the write side.

    If ``prune=True``, any current origin for ``(source, corpus)`` whose
    ``uri`` is not in the input set is swept the same way (use for "this is
    now the complete corpus" semantics).

    The Cypher write step only pushes nodes whose origin is in the
    ``touched_paths`` set. Untouched origins, their nodes, and rels between
    them are unaffected.

    Returns ``(graph, origins_by_prefix, ExtractStats)``. ``graph`` is
    ``None`` when nothing changed (no work done).
    """
    from .build import build_kg

    paths = [Path(p) for p in sv_paths]

    stats_e = ExtractStats(write_stats=None)
    seen: dict[str, int] = {}
    new_uris: set[str] = set()
    touched_paths: list[Path] = []
    origins_by_prefix: dict[str, OriginRef] = {}
    touched_origin_ids: set[str] = set()
    prefix_for_path: dict[str, str] = {}

    for p in paths:
        prefix = _prefix_for_path(p, seen)
        prefix_for_path[str(p)] = prefix
        uri = str(p.resolve())
        new_uris.add(uri)
        new_sha = _sha_of(p)
        existing = store.find_current_origin(uri=uri, source=source, corpus=corpus)
        if existing is not None and existing.sha256 == new_sha:
            origins_by_prefix[prefix] = existing
            stats_e.unchanged_paths.append(uri)
            continue
        if existing is not None and existing.sha256 != new_sha:
            store.delete_origin_subtree(existing.id)
        touched_paths.append(p)
        stats_e.touched_paths.append(uri)

    if prune:
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

    if not touched_paths:
        return None, origins_by_prefix, stats_e

    for p in touched_paths:
        prefix = prefix_for_path[str(p)]
        ref = store.snapshot_file(p, source=source, corpus=corpus, lang=lang)
        origins_by_prefix[prefix] = ref
        touched_origin_ids.add(ref.id)

    # Whole-corpus build — SV semantic resolution is cross-file.
    graph, _trees, _comp = build_kg(paths)
    filtered = _filter_graph_to_origins(
        graph, origins_by_prefix, touched_origin_ids
    )
    write_stats = write_graph(
        store, filtered, source=source, corpus=corpus, origins=origins_by_prefix
    )
    stats_e.write_stats = write_stats
    return graph, origins_by_prefix, stats_e


def _filter_graph_to_origins(
    graph: dict[str, Any],
    origins_by_prefix: dict[str, OriginRef],
    touched_origin_ids: set[str],
) -> dict[str, Any]:
    """Subset ``graph`` to nodes whose resolved origin is in ``touched_origin_ids``.

    Uses :func:`_resolve_origins_for_nodes` to determine each node's origin
    (same logic the writer would apply), then drops nodes outside the
    touched set and edges whose endpoints fall outside it.
    """
    nodes: list[dict[str, Any]] = graph.get("nodes", [])
    edges: list[dict[str, Any]] = graph.get("edges", [])
    order: list[str] = graph.get("order", []) or []

    node_origin = _resolve_origins_for_nodes(nodes, edges, origins_by_prefix, order)
    keep_ids = {
        n["id"] for n in nodes if node_origin[n["id"]].id in touched_origin_ids
    }
    kept_nodes = [n for n in nodes if n["id"] in keep_ids]
    kept_edges = [
        e for e in edges if e.get("src") in keep_ids and e.get("dst") in keep_ids
    ]
    kept_order = [oid for oid in order if oid in keep_ids]
    return {"nodes": kept_nodes, "edges": kept_edges, "order": kept_order}


__all__ = [
    "write_graph",
    "build_and_store",
    "extract",
    "WriteStats",
    "ExtractStats",
    "EDGE_TABLE_MAP",
]
