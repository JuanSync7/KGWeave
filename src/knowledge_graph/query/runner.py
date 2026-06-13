"""Execute a compiled :class:`QueryIntent` against a :class:`KGStore`.

Anchor resolution semantics:

* ``AnchorRef(id=...)`` — must match 0 or 1 node. 0 matches → empty
  ``QueryResult`` (not an error). >1 cannot happen: ``id`` is a primary
  key.
* ``AnchorRef(by_kind_name=(k, n))`` — must match 0 or 1 node. 0 matches
  → empty result. >1 matches → :class:`AmbiguousAnchor`.
"""

from __future__ import annotations

import json
from typing import Any

from knowledge_graph.query.compiler import NODE_RETURN_FIELDS, compile_intent
from knowledge_graph.query.errors import classify_cypher_error
from knowledge_graph.query.intents import (
    AnchorRef,
    FilterIntent,
    NeighborhoodIntent,
    QueryIntent,
    RawCypher,
    TraverseIntent,
)
from knowledge_graph.query.results import (
    EdgeView,
    NodeView,
    PathView,
    QueryResult,
)
from knowledge_graph.schemas import Span

__all__ = ["run_intent", "AmbiguousAnchor"]


class AmbiguousAnchor(LookupError):
    """Raised when an ``AnchorRef(by_kind_name=...)`` matches >1 node."""


# --------------------------------------------------------------- helpers


def _decode_payload(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _row_to_nodeview(row: list[Any]) -> NodeView:
    (
        nid, kind, category, name, source, corpus, origin_id,
        s_off, e_off, s_line, e_line, s_col, e_col, payload,
    ) = row
    span: Span | None = None
    if s_off is not None and s_off != -1:
        span = Span(
            origin_id=origin_id or "",
            start_offset=int(s_off),
            end_offset=int(e_off),
            start_line=int(s_line or 0),
            end_line=int(e_line or 0),
            start_col=int(s_col or 0),
            end_col=int(e_col or 0),
        )
    return NodeView(
        id=nid,
        kind=kind,
        category=category,
        name=name,
        source=source,
        corpus=corpus,
        origin_id=origin_id,
        span=span,
        payload=_decode_payload(payload),
    )


def _node_dict_to_view(d: dict[str, Any]) -> NodeView:
    """Convert a Kuzu ``nodes(p)`` element (dict) to a NodeView."""
    s_off = d.get("start_offset")
    origin_id = d.get("origin_id")
    span: Span | None = None
    if s_off is not None and s_off != -1:
        span = Span(
            origin_id=origin_id or "",
            start_offset=int(s_off),
            end_offset=int(d.get("end_offset", 0) or 0),
            start_line=int(d.get("start_line", 0) or 0),
            end_line=int(d.get("end_line", 0) or 0),
            start_col=int(d.get("start_col", 0) or 0),
            end_col=int(d.get("end_col", 0) or 0),
        )
    return NodeView(
        id=d.get("id", ""),
        kind=d.get("kind", ""),
        category=d.get("category", ""),
        name=d.get("name"),
        source=d.get("source", ""),
        corpus=d.get("corpus", ""),
        origin_id=origin_id,
        span=span,
        payload=_decode_payload(d.get("payload")),
    )


# ---- anchor resolution -------------------------------------------------


def _resolve_anchor(conn, anchor: AnchorRef) -> str | None:
    """Return the resolved node id, or ``None`` if the anchor matches zero rows."""
    if anchor.id is not None:
        res = conn.execute(
            "MATCH (n:Node) WHERE n.id = $id RETURN n.id LIMIT 1",
            {"id": anchor.id},
        )
        if not res.has_next():
            return None
        return res.get_next()[0]
    assert anchor.by_kind_name is not None
    kind, name = anchor.by_kind_name
    res = conn.execute(
        "MATCH (n:Node) WHERE n.kind = $k AND n.name = $n RETURN n.id LIMIT 2",
        {"k": kind, "n": name},
    )
    hits: list[str] = []
    while res.has_next():
        hits.append(res.get_next()[0])
    if not hits:
        return None
    if len(hits) > 1:
        raise AmbiguousAnchor(
            f"by_kind_name=({kind!r}, {name!r}) matched {len(hits)}+ nodes"
        )
    return hits[0]


# ---- per-intent execution ---------------------------------------------


def _run_filter(conn, intent: FilterIntent) -> QueryResult:
    cypher, params = compile_intent(intent)
    res = conn.execute(cypher, params)
    nodes: list[NodeView] = []
    while res.has_next():
        nodes.append(_row_to_nodeview(res.get_next()))
    return QueryResult(intent_kind="filter", nodes=nodes)


def _drain_paths(res) -> list[PathView]:
    paths: list[PathView] = []
    while res.has_next():
        row = res.get_next()
        raw_nodes = row[0] or []
        raw_edges = row[1] or []
        nodes = [_node_dict_to_view(d) for d in raw_nodes]
        edges: list[EdgeView] = []
        node_ids = [n.id for n in nodes]
        for i, e in enumerate(raw_edges):
            props = {
                k: v for k, v in e.items() if not k.startswith("_")
            }
            src = node_ids[i] if i < len(node_ids) else ""
            dst = node_ids[i + 1] if i + 1 < len(node_ids) else ""
            edges.append(EdgeView(
                src=src,
                dst=dst,
                type=e.get("_label", ""),
                properties=props,
            ))
        paths.append(PathView(nodes=nodes, edges=edges))
    return paths


def _run_traverse(conn, intent: TraverseIntent) -> QueryResult:
    if _resolve_anchor(conn, intent.anchor) is None:
        return QueryResult(intent_kind="traverse")
    cypher, params = compile_intent(intent)
    res = conn.execute(cypher, params)
    return QueryResult(intent_kind="traverse", paths=_drain_paths(res))


def _run_neighborhood(conn, intent: NeighborhoodIntent) -> QueryResult:
    if _resolve_anchor(conn, intent.anchor) is None:
        return QueryResult(intent_kind="neighborhood")
    cypher, params = compile_intent(intent)
    res = conn.execute(cypher, params)
    return QueryResult(intent_kind="neighborhood", paths=_drain_paths(res))


def _is_node_cell(value: Any) -> bool:
    """A Kuzu node value comes back as a dict carrying ``_id``/``_label``."""
    return (
        isinstance(value, dict)
        and "_id" in value
        and value.get("_label") == "Node"
    )


def _hydrate_cell(value: Any) -> Any:
    """Hydrate a node-valued cell to a :class:`NodeView`; scalars pass through."""
    if _is_node_cell(value):
        return _node_dict_to_view(value)
    return value


def _run_raw(conn, intent: RawCypher) -> QueryResult:
    cypher, params = compile_intent(intent)
    try:
        res = conn.execute(cypher, params)
    except Exception as exc:  # noqa: BLE0001 — classify, never leak raw
        raise classify_cypher_error(exc) from exc
    col_names: list[str] = []
    try:
        col_names = list(res.get_column_names())
    except Exception:
        col_names = []
    rows: list[dict[str, Any]] = []
    while res.has_next():
        row = [_hydrate_cell(v) for v in res.get_next()]
        if col_names and len(col_names) == len(row):
            rows.append(dict(zip(col_names, row)))
        else:
            rows.append({f"col_{i}": v for i, v in enumerate(row)})
    return QueryResult(intent_kind="raw", rows=rows)


# ------------------------------------------------------------------ entry


def run_intent(store, intent: QueryIntent) -> QueryResult:
    """Execute ``intent`` against ``store`` and return a :class:`QueryResult`."""
    conn = store.conn
    if isinstance(intent, FilterIntent):
        return _run_filter(conn, intent)
    if isinstance(intent, TraverseIntent):
        return _run_traverse(conn, intent)
    if isinstance(intent, NeighborhoodIntent):
        return _run_neighborhood(conn, intent)
    if isinstance(intent, RawCypher):
        return _run_raw(conn, intent)
    raise TypeError(f"unknown intent type: {type(intent).__name__}")


# Keep an export for NODE_RETURN_FIELDS for downstream pinning.
_ = NODE_RETURN_FIELDS
