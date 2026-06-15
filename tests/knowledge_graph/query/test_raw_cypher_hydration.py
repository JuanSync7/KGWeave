"""Raw-Cypher node hydration + structured ``CypherError`` on the raw path."""

from __future__ import annotations

import pytest

from knowledge_graph.query import (
    CypherError,
    NodeView,
    RawCypher,
    run_intent,
)


def test_node_cell_is_hydrated_to_nodeview(query_store):
    """``RETURN n`` of a whole node yields a NodeView cell, not a raw dict."""
    result = run_intent(query_store, RawCypher(
        cypher="MATCH (n:Node) WHERE n.id = $id RETURN n",
        parameters={"id": "M1"},
    ))
    assert len(result.rows) == 1
    cell = result.rows[0]["n"]
    assert isinstance(cell, NodeView)
    assert cell.id == "M1"
    assert cell.kind == "Module"
    assert cell.name == "top"


def test_node_and_scalar_cells_coexist(query_store):
    """A node cell hydrates; a scalar cell stays scalar in the same row."""
    result = run_intent(query_store, RawCypher(
        cypher="MATCH (n:Node) WHERE n.id = $id RETURN n, n.id AS nid",
        parameters={"id": "B1"},
    ))
    row = result.rows[0]
    assert isinstance(row["n"], NodeView)
    assert row["nid"] == "B1"
    # Blob payload round-trips through hydration.
    assert row["n"].payload == {"k": "v"}


def test_scalar_only_rows_unchanged(query_store):
    """Pure-scalar projections keep returning raw scalar dict rows."""
    result = run_intent(query_store, RawCypher(
        cypher="MATCH (n:Node) WHERE n.kind = $k RETURN n.id ORDER BY n.id",
        parameters={"k": "Port"},
    ))
    ids = [row["n.id"] for row in result.rows]
    assert ids == ["pA", "pB", "pC"]


def test_zero_match_is_empty_success_not_error(query_store):
    """A valid query that matches nothing returns an empty, successful result."""
    result = run_intent(query_store, RawCypher(
        cypher="MATCH (n:Node) WHERE n.id = $id RETURN n",
        parameters={"id": "does-not-exist"},
    ))
    assert result.intent_kind == "raw"
    assert result.rows == []


def test_unknown_property_raises_classified_cypher_error(query_store):
    """A near-miss property name → unknown_property + a difflib suggestion."""
    with pytest.raises(CypherError) as exc:
        run_intent(query_store, RawCypher(
            cypher="MATCH (n:Node) WHERE n.naem = $x RETURN n",
            parameters={"x": "top"},
        ))
    err = exc.value
    assert err.kind == "unknown_property"
    assert err.kind != "engine"
    assert err.suggestion == "name"


def test_unknown_edge_raises_classified_cypher_error(query_store):
    with pytest.raises(CypherError) as exc:
        run_intent(query_store, RawCypher(
            cypher="MATCH (n:Node)-[:DRIVE]->(m:Node) RETURN n",
        ))
    err = exc.value
    assert err.kind == "unknown_edge"
    assert err.suggestion == "DRIVES"


def test_unknown_label_raises_classified_cypher_error(query_store):
    with pytest.raises(CypherError) as exc:
        run_intent(query_store, RawCypher(
            cypher="MATCH (n:Nodes) RETURN n",
        ))
    err = exc.value
    assert err.kind == "unknown_label"
    assert err.suggestion == "Node"


def test_syntax_error_is_classified(query_store):
    with pytest.raises(CypherError) as exc:
        run_intent(query_store, RawCypher(
            cypher="MATCH (n:Node RETURN n",
        ))
    assert exc.value.kind == "syntax"
