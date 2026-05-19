"""``AnchorRef`` validation + compile + resolution semantics."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from knowledge_graph.query import (
    AnchorRef,
    NeighborhoodIntent,
    QueryIntent,
    RawCypher,
    TraverseIntent,
    compile_intent,
    run_intent,
)
from knowledge_graph.query.intents import FilterIntent


def test_anchor_requires_exactly_one_field():
    with pytest.raises(ValidationError):
        AnchorRef()
    with pytest.raises(ValidationError):
        AnchorRef(id="x", by_kind_name=("Module", "top"))


def test_anchor_id_compiles_to_id_predicate():
    intent = TraverseIntent(anchor=AnchorRef(id="M1"), via=["HAS_PORT"])
    cypher, params = compile_intent(intent)
    assert "a.id = $anchor_id" in cypher
    assert params["anchor_id"] == "M1"


def test_anchor_by_kind_name_compiles_to_kind_name_predicate():
    intent = TraverseIntent(
        anchor=AnchorRef(by_kind_name=("Module", "top")),
        via=["HAS_PORT"],
    )
    cypher, params = compile_intent(intent)
    assert "a.kind = $anchor_kind AND a.name = $anchor_name" in cypher
    assert params["anchor_kind"] == "Module"
    assert params["anchor_name"] == "top"


def test_anchor_by_kind_name_resolves_in_runner(query_store):
    result = run_intent(query_store, TraverseIntent(
        anchor=AnchorRef(by_kind_name=("Module", "top")),
        via=["HAS_PORT"],
        depth=1,
    ))
    endpoints = sorted({p.nodes[-1].id for p in result.paths})
    assert endpoints == ["pA", "pB"]


def test_intent_union_json_roundtrip():
    from pydantic import TypeAdapter

    adapter: TypeAdapter[QueryIntent] = TypeAdapter(QueryIntent)
    for intent in (
        FilterIntent(node_kind="Port", limit=5),
        TraverseIntent(anchor=AnchorRef(id="X"), via=["DRIVES"]),
        NeighborhoodIntent(anchor=AnchorRef(id="X"), radius=2),
        RawCypher(cypher="MATCH (n) RETURN n"),
    ):
        blob = adapter.dump_json(intent)
        restored = adapter.validate_json(blob)
        # discriminator preserves the concrete class
        assert type(restored) is type(intent)
        # field equality
        assert json.loads(blob) == json.loads(adapter.dump_json(restored))
