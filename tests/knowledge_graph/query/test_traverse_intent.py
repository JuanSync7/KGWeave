"""Golden Cypher + execution tests for ``TraverseIntent``."""

from __future__ import annotations

import pytest

from knowledge_graph.query import (
    AnchorRef,
    TraverseIntent,
    compile_intent,
    run_intent,
)


def test_traverse_fwd_depth1_single_rel_golden():
    intent = TraverseIntent(
        anchor=AnchorRef(id="M1"),
        via=["HAS_PORT"],
        direction="fwd",
        depth=1,
        limit=50,
    )
    cypher, params = compile_intent(intent)
    assert cypher == (
        "MATCH p = (a:Node)-[:HAS_PORT*1..1]->(b:Node) "
        "WHERE a.id = $anchor_id "
        "RETURN nodes(p), rels(p) LIMIT $limit"
    )
    assert params == {"anchor_id": "M1", "limit": 50}


def test_traverse_fwd_depth2_multi_rel_golden():
    intent = TraverseIntent(
        anchor=AnchorRef(id="pA"),
        via=["DRIVES", "READS"],
        direction="fwd",
        depth=2,
    )
    cypher, _params = compile_intent(intent)
    assert "[:DRIVES|READS*1..2]->" in cypher
    assert "WHERE a.id = $anchor_id" in cypher


def test_traverse_rev_uses_left_arrow():
    intent = TraverseIntent(
        anchor=AnchorRef(id="pC"),
        via=["READS"],
        direction="rev",
        depth=1,
    )
    cypher, _ = compile_intent(intent)
    assert "<-[:READS*1..1]-" in cypher


def test_traverse_both_uses_undirected():
    intent = TraverseIntent(
        anchor=AnchorRef(id="pB"),
        via=["DRIVES"],
        direction="both",
        depth=1,
    )
    cypher, _ = compile_intent(intent)
    assert "-[:DRIVES*1..1]-(b:Node)" in cypher
    assert "->" not in cypher.split("(b:Node)")[0][-5:]


def test_traverse_by_kind_name_anchor_params():
    intent = TraverseIntent(
        anchor=AnchorRef(by_kind_name=("Module", "top")),
        via=["HAS_PORT"],
    )
    cypher, params = compile_intent(intent)
    assert "a.kind = $anchor_kind AND a.name = $anchor_name" in cypher
    assert params["anchor_kind"] == "Module"
    assert params["anchor_name"] == "top"


def test_traverse_runs_returns_paths_from_M1(query_store):
    result = run_intent(query_store, TraverseIntent(
        anchor=AnchorRef(id="M1"),
        via=["HAS_PORT"],
        depth=1,
    ))
    assert result.intent_kind == "traverse"
    assert len(result.paths) == 2
    endpoints = sorted(p.nodes[-1].id for p in result.paths)
    assert endpoints == ["pA", "pB"]
    for p in result.paths:
        assert p.edges[0].type == "HAS_PORT"
        assert p.edges[0].src == "M1"


def test_traverse_depth2_chains_drives(query_store):
    result = run_intent(query_store, TraverseIntent(
        anchor=AnchorRef(id="pA"),
        via=["DRIVES"],
        depth=2,
    ))
    endpoints = sorted({p.nodes[-1].id for p in result.paths})
    assert "B1" in endpoints
    assert "pB" in endpoints


def test_traverse_rev_finds_caller(query_store):
    result = run_intent(query_store, TraverseIntent(
        anchor=AnchorRef(id="F1"),
        via=["CALLS"],
        direction="rev",
        depth=1,
    ))
    starts = sorted({p.nodes[-1].id for p in result.paths})
    assert starts == ["M1"]


def test_traverse_missing_anchor_returns_empty(query_store):
    result = run_intent(query_store, TraverseIntent(
        anchor=AnchorRef(id="nope"),
        via=["HAS_PORT"],
    ))
    assert result.paths == []


def test_traverse_ambiguous_by_kind_name_raises(query_store):
    from knowledge_graph.query.runner import AmbiguousAnchor
    # Add a duplicate (Module, "top") so by_kind_name resolves to >1 node.
    query_store.conn.execute(
        "CREATE (n:Node {id: 'D1', kind: 'Module', category: 'semantic', "
        "name: 'top', source: 'sv', corpus: 'fixtures', origin_id: 'O1', "
        "start_offset: -1, end_offset: -1, start_line: 0, end_line: 0, "
        "start_col: 0, end_col: 0, payload: '{}'})"
    )
    with pytest.raises(AmbiguousAnchor):
        run_intent(query_store, TraverseIntent(
            anchor=AnchorRef(by_kind_name=("Module", "top")),
            via=["HAS_PORT"],
        ))
