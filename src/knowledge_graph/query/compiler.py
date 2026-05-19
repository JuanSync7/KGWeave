"""``compile_intent(intent) -> (cypher, params)``.

Every intent compiles to a single parameterized Cypher statement. Param
names follow a stable convention so golden tests can pin exact strings:

* Filter:        ``$kind, $category, $name, $source, $corpus, $origin_id, $limit``
* Traverse:      ``$anchor_id`` or ``$anchor_kind/$anchor_name``, ``$limit``
* Neighborhood:  same anchor params, ``$limit``
* Raw:           passed through verbatim, parameters dict forwarded.

Variable-length over a rel-type union is rendered as ``-[:A|B|...*1..N]->``.
Kuzu 0.11 supports this syntax (probed at port time); if a future
upgrade breaks it, swap to a ``UNION`` of N single-type queries.
"""

from __future__ import annotations

from typing import Any

from knowledge_graph.query.intents import (
    ALL_EDGE_TYPES,
    AnchorRef,
    FilterIntent,
    NeighborhoodIntent,
    QueryIntent,
    RawCypher,
    TraverseIntent,
)
from knowledge_graph.query.readonly import assert_read_only

__all__ = ["compile_intent", "NODE_RETURN_FIELDS"]


# The canonical projection used wherever we return a :Node. Keeping this
# in one place makes the runner's row → NodeView mapping a fixed offset.
NODE_RETURN_FIELDS: tuple[str, ...] = (
    "id",
    "kind",
    "category",
    "name",
    "source",
    "corpus",
    "origin_id",
    "start_offset",
    "end_offset",
    "start_line",
    "end_line",
    "start_col",
    "end_col",
    "payload",
)


def _node_return(alias: str) -> str:
    """Return ``alias.id, alias.kind, ...`` for the canonical projection."""
    return ", ".join(f"{alias}.{f}" for f in NODE_RETURN_FIELDS)


# ----------------------------------------------------------------- filter


def _compile_filter(intent: FilterIntent) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}

    # Order is fixed for deterministic golden Cypher.
    field_to_param = (
        ("kind", "kind", intent.node_kind),
        ("category", "category", intent.category),
        ("name", "name", intent.name),
        ("source", "source", intent.source),
        ("corpus", "corpus", intent.corpus),
        ("origin_id", "origin_id", intent.origin_id),
    )
    for column, pname, value in field_to_param:
        if value is not None:
            clauses.append(f"n.{column} = ${pname}")
            params[pname] = value

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params["limit"] = intent.limit
    cypher = (
        f"MATCH (n:Node){where} RETURN {_node_return('n')} LIMIT $limit"
    )
    return cypher, params


# --------------------------------------------------------------- anchors


def _anchor_predicate(anchor: AnchorRef, alias: str) -> tuple[str, dict[str, Any]]:
    """Render the ``WHERE`` predicate that pins ``alias`` to the anchor."""
    if anchor.id is not None:
        return f"{alias}.id = $anchor_id", {"anchor_id": anchor.id}
    assert anchor.by_kind_name is not None  # validator guarantees
    kind, name = anchor.by_kind_name
    return (
        f"{alias}.kind = $anchor_kind AND {alias}.name = $anchor_name",
        {"anchor_kind": kind, "anchor_name": name},
    )


# --------------------------------------------------------------- traverse


def _rel_pattern(via: list[str], depth: int, direction: str) -> str:
    """Render ``-[:A|B*1..N]->`` (or reversed / undirected) fragment."""
    rels = "|".join(via)
    body = f"[:{rels}*1..{depth}]"
    if direction == "fwd":
        return f"-{body}->"
    if direction == "rev":
        return f"<-{body}-"
    return f"-{body}-"  # both


def _compile_traverse(intent: TraverseIntent) -> tuple[str, dict[str, Any]]:
    pred, params = _anchor_predicate(intent.anchor, "a")
    rel = _rel_pattern(list(intent.via), intent.depth, intent.direction)
    params["limit"] = intent.limit
    cypher = (
        f"MATCH p = (a:Node){rel}(b:Node) "
        f"WHERE {pred} "
        f"RETURN nodes(p), rels(p) LIMIT $limit"
    )
    return cypher, params


# ----------------------------------------------------------- neighborhood


def _compile_neighborhood(intent: NeighborhoodIntent) -> tuple[str, dict[str, Any]]:
    pred, params = _anchor_predicate(intent.anchor, "a")
    rels = "|".join(ALL_EDGE_TYPES)
    params["limit"] = intent.limit
    cypher = (
        f"MATCH p = (a:Node)-[:{rels}*1..{intent.radius}]-(b:Node) "
        f"WHERE {pred} "
        f"RETURN nodes(p), rels(p) LIMIT $limit"
    )
    return cypher, params


# ------------------------------------------------------------------- raw


def _compile_raw(intent: RawCypher) -> tuple[str, dict[str, Any]]:
    assert_read_only(intent.cypher)
    return intent.cypher, dict(intent.parameters)


# ----------------------------------------------------------------- entry


def compile_intent(intent: QueryIntent) -> tuple[str, dict[str, Any]]:
    """Compile any ``QueryIntent`` to ``(cypher, params)``."""
    if isinstance(intent, FilterIntent):
        return _compile_filter(intent)
    if isinstance(intent, TraverseIntent):
        return _compile_traverse(intent)
    if isinstance(intent, NeighborhoodIntent):
        return _compile_neighborhood(intent)
    if isinstance(intent, RawCypher):
        return _compile_raw(intent)
    raise TypeError(f"unknown intent type: {type(intent).__name__}")
