"""Connector protocol + registry tests."""

from __future__ import annotations

import pytest

import knowledge_graph as kg


def _semantic_node_count(store) -> int:
    res = store.conn.execute(
        "MATCH (n:Node) WHERE n.category = 'semantic' RETURN count(*)"
    )
    return int(res.get_next()[0])


def _contains_edge_count(store) -> int:
    res = store.conn.execute("MATCH ()-[r:CONTAINS]->() RETURN count(*)")
    return int(res.get_next()[0])


def test_register_and_run_connector(facade_store) -> None:
    c = kg.SemanticSelfRefConnector()
    kg.register_connector(c)
    sem = _semantic_node_count(facade_store)
    assert sem > 0
    before = _contains_edge_count(facade_store)
    result = kg.run_connectors(facade_store, only=[c.name])
    assert result[c.name] == sem
    after = _contains_edge_count(facade_store)
    assert after - before == sem
    # Idempotency: MERGE collapses on second run.
    kg.run_connectors(facade_store, only=[c.name])
    assert _contains_edge_count(facade_store) == after


def test_connector_requires_check(empty_store) -> None:
    """A connector requiring 'sv' but extract was never run → clear error."""
    class _Needs(kg.SemanticSelfRefConnector):  # type: ignore[misc]
        name = "needs-sv-conn"

    c = _Needs()
    kg.register_connector(c)
    with pytest.raises(kg.ConnectorRequirementError):
        kg.run_connectors(empty_store, only=[c.name])
