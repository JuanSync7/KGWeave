"""Golden Cypher + execution tests for ``NeighborhoodIntent``."""

from __future__ import annotations

from knowledge_graph.query import (
    ALL_EDGE_TYPES,
    AnchorRef,
    NeighborhoodIntent,
    compile_intent,
    run_intent,
)


def test_neighborhood_radius1_golden():
    intent = NeighborhoodIntent(anchor=AnchorRef(id="M1"), radius=1, limit=100)
    cypher, params = compile_intent(intent)
    rels = "|".join(ALL_EDGE_TYPES)
    expected = (
        f"MATCH p = (a:Node)-[:{rels}*1..1]-(b:Node) "
        "WHERE a.id = $anchor_id "
        "RETURN nodes(p), rels(p) LIMIT $limit"
    )
    assert cypher == expected
    assert params == {"anchor_id": "M1", "limit": 100}


def test_neighborhood_radius2_uses_all_rels_undirected():
    intent = NeighborhoodIntent(anchor=AnchorRef(id="M1"), radius=2)
    cypher, _ = compile_intent(intent)
    assert "*1..2" in cypher
    assert "->" not in cypher  # undirected
    for rel in ALL_EDGE_TYPES:
        assert rel in cypher


def test_neighborhood_runs_radius1_returns_direct_neighbors(query_store):
    result = run_intent(query_store, NeighborhoodIntent(
        anchor=AnchorRef(id="M1"), radius=1,
    ))
    assert result.intent_kind == "neighborhood"
    neighbors = {p.nodes[-1].id for p in result.paths}
    # Direct neighbors of M1: pA, pB (HAS_PORT), F1 (HAS_FUNCTION + CALLS).
    assert {"pA", "pB", "F1"} <= neighbors


def test_neighborhood_radius2_expands_through_drives(query_store):
    result = run_intent(query_store, NeighborhoodIntent(
        anchor=AnchorRef(id="M1"), radius=2,
    ))
    reached = {n.id for p in result.paths for n in p.nodes}
    # B1 is 2 hops from M1: M1-HAS_PORT->pA-DRIVES->B1
    assert "B1" in reached


def test_neighborhood_empty_anchor_returns_empty(query_store):
    result = run_intent(query_store, NeighborhoodIntent(
        anchor=AnchorRef(id="missing"), radius=2,
    ))
    assert result.paths == []
