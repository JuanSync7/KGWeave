"""Stage 1 schema additions: confidence tier, resolved flag, is_test on Entity.

These fields support splitting an audit-precision view from a recall-oriented
test-completeness view over the same KG without dual ingestion paths.
"""

from __future__ import annotations

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple


def test_triple_default_confidence_is_high() -> None:
    t = Triple(subject="a", predicate="rel", object="b")
    assert t.confidence_tier == "high"


def test_triple_default_resolved_is_true() -> None:
    t = Triple(subject="a", predicate="rel", object="b")
    assert t.resolved is True


def test_triple_can_set_low_confidence() -> None:
    t = Triple(subject="a", predicate="rel", object="b", confidence_tier="low")
    assert t.confidence_tier == "low"


def test_triple_can_mark_unresolved() -> None:
    t = Triple(subject="a", predicate="rel", object="b", resolved=False)
    assert t.resolved is False


def test_entity_default_is_test_is_none() -> None:
    e = Entity(name="foo", type="SW_Test")
    assert e.is_test is None


def test_entity_can_set_is_test_true() -> None:
    e = Entity(name="foo", type="SW_Test", is_test=True)
    assert e.is_test is True


def test_backend_persists_confidence_on_edge() -> None:
    backend = NetworkXBackend()
    backend.upsert_entities(
        [
            Entity(name="test_a", type="SW_Test"),
            Entity(name="mod_b", type="RTL_Module"),
        ]
    )
    backend.upsert_triples(
        [
            Triple(
                subject="test_a",
                predicate="tests_module",
                object="mod_b",
                confidence_tier="medium",
                resolved=False,
            )
        ]
    )
    edge_data = backend.graph["test_a"]["mod_b"]["tests_module"]
    assert edge_data["confidence_tier"] == "medium"
    assert edge_data["resolved"] is False


def test_backend_persists_is_test_on_node() -> None:
    backend = NetworkXBackend()
    backend.upsert_entities(
        [Entity(name="crt0.c", type="SW_Test", is_test=False)]
    )
    node_data = backend.graph.nodes["crt0.c"]
    assert node_data["is_test"] is False
