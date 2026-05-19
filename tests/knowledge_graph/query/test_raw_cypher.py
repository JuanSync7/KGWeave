"""Tests for the ``RawCypher`` escape hatch."""

from __future__ import annotations

import pytest

from knowledge_graph.query import (
    RawCypher,
    ReadOnlyViolation,
    compile_intent,
    run_intent,
)


def test_raw_compile_passthrough_with_params():
    intent = RawCypher(
        cypher="MATCH (n:Node) WHERE n.kind = $k RETURN n.id",
        parameters={"k": "Port"},
    )
    cypher, params = compile_intent(intent)
    assert cypher == "MATCH (n:Node) WHERE n.kind = $k RETURN n.id"
    assert params == {"k": "Port"}


def test_raw_runs_against_fixture(query_store):
    result = run_intent(query_store, RawCypher(
        cypher="MATCH (n:Node) WHERE n.kind = $k RETURN n.id ORDER BY n.id",
        parameters={"k": "Port"},
    ))
    assert result.intent_kind == "raw"
    ids = [row["n.id"] for row in result.rows]
    assert ids == ["pA", "pB", "pC"]


def test_raw_param_string_with_banned_keyword_in_value_is_allowed(query_store):
    # The string 'CREATE' lives in a parameter value, not in the query text.
    result = run_intent(query_store, RawCypher(
        cypher="MATCH (n:Node) WHERE n.name = $bad RETURN n.id",
        parameters={"bad": "CREATE"},
    ))
    assert result.rows == []  # no node named 'CREATE'


def test_raw_write_keyword_is_rejected():
    with pytest.raises(ReadOnlyViolation):
        compile_intent(RawCypher(cypher="CREATE (n:Node {id: 'x'})"))
