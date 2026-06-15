"""Golden Cypher + result-shape tests for ``FilterIntent``."""

from __future__ import annotations

from knowledge_graph.query import FilterIntent, compile_intent, run_intent


def _expected_return(alias: str = "n") -> str:
    fields = (
        "id", "kind", "category", "name", "source", "corpus", "origin_id",
        "start_offset", "end_offset", "start_line", "end_line",
        "start_col", "end_col", "payload",
    )
    return ", ".join(f"{alias}.{f}" for f in fields)


def test_filter_no_predicates_compiles_to_unrestricted_match():
    intent = FilterIntent(limit=50)
    cypher, params = compile_intent(intent)
    assert cypher == f"MATCH (n:Node) RETURN {_expected_return()} LIMIT $limit"
    assert params == {"limit": 50}


def test_filter_full_predicates_golden():
    intent = FilterIntent(
        node_kind="Port",
        category="semantic",
        name="a",
        source="sv",
        corpus="fixtures",
        origin_id="O1",
        limit=10,
    )
    cypher, params = compile_intent(intent)
    expected_cypher = (
        "MATCH (n:Node) WHERE "
        "n.kind = $kind AND n.category = $category AND n.name = $name "
        "AND n.source = $source AND n.corpus = $corpus "
        "AND n.origin_id = $origin_id "
        f"RETURN {_expected_return()} LIMIT $limit"
    )
    assert cypher == expected_cypher
    assert params == {
        "kind": "Port", "category": "semantic", "name": "a",
        "source": "sv", "corpus": "fixtures", "origin_id": "O1",
        "limit": 10,
    }


def test_filter_runs_against_fixture_returns_only_ports(query_store):
    result = run_intent(query_store, FilterIntent(node_kind="Port"))
    assert result.intent_kind == "filter"
    ids = sorted(n.id for n in result.nodes)
    assert ids == ["pA", "pB", "pC"]
    for n in result.nodes:
        assert n.kind == "Port"
        assert n.source == "sv"


def test_filter_empty_result_is_empty_not_error(query_store):
    result = run_intent(query_store, FilterIntent(node_kind="Doesnotexist"))
    assert result.nodes == []


def test_filter_payload_decoded_to_dict(query_store):
    result = run_intent(query_store, FilterIntent(category="blob"))
    assert len(result.nodes) == 1
    assert result.nodes[0].payload == {"k": "v"}


def test_filter_span_present_when_offsets_set(query_store):
    result = run_intent(query_store, FilterIntent(node_kind="Module", name="top"))
    assert len(result.nodes) == 1
    span = result.nodes[0].span
    assert span is not None and span.start_offset == 0 and span.end_offset == 10


def test_filter_span_none_when_offset_is_negative_one(query_store):
    result = run_intent(query_store, FilterIntent(node_kind="Function"))
    assert len(result.nodes) == 1
    assert result.nodes[0].span is None
