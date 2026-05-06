# @summary
# Tests the KGAdminClient Protocol contract and its default implementations
# on GraphStorageBackend. Verifies count_by_source_key, delete_by_source_key,
# and health behave correctly on NetworkXBackend.
# Exports: (test module)
# Deps: pytest, src.knowledge_graph.backends.networkx_backend,
#       src.knowledge_graph.common.protocols
# @end-summary
"""Step 4: KGAdminClient Protocol contract tests."""

from __future__ import annotations

import pytest

from kgweave.knowledge_graph.backend import GraphStorageBackend, RemovalStats
from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.protocols import KGAdminClient
from kgweave.knowledge_graph.common.schemas import Entity, Triple


@pytest.fixture
def populated_backend() -> NetworkXBackend:
    backend = NetworkXBackend()
    backend.upsert_entities(
        [
            Entity(name="Alpha", type="Concept", sources=["doc1.md"]),
            Entity(name="Beta", type="Concept", sources=["doc1.md", "doc2.md"]),
            Entity(name="Gamma", type="Concept", sources=["doc2.md"]),
        ]
    )
    backend.upsert_triples(
        [
            Triple(subject="Alpha", object="Beta", predicate="related", source="doc1.md"),
            Triple(subject="Beta", object="Gamma", predicate="related", source="doc2.md"),
        ]
    )
    return backend


def test_networkx_backend_satisfies_admin_protocol(populated_backend: NetworkXBackend) -> None:
    assert isinstance(populated_backend, KGAdminClient)


def test_count_by_source_key_returns_entity_count(populated_backend: NetworkXBackend) -> None:
    assert populated_backend.count_by_source_key("doc1.md") == 2  # Alpha, Beta
    assert populated_backend.count_by_source_key("doc2.md") == 2  # Beta, Gamma
    assert populated_backend.count_by_source_key("missing.md") == 0


def test_delete_by_source_key_returns_removal_stats(populated_backend: NetworkXBackend) -> None:
    stats = populated_backend.delete_by_source_key("doc1.md")
    assert isinstance(stats, RemovalStats)
    assert stats.entities_removed == 1  # Alpha (sole source)
    assert stats.entities_pruned == 1   # Beta (also in doc2)
    assert stats.triples_removed == 1   # Alpha->Beta edge
    assert populated_backend.count_by_source_key("doc1.md") == 0


def test_health_returns_dict_with_required_keys(populated_backend: NetworkXBackend) -> None:
    health = populated_backend.health()
    assert isinstance(health, dict)
    assert "nodes" in health
    assert "edges" in health
    assert "backend" in health
    assert health["nodes"] == 3
    assert health["edges"] == 2
    assert health["backend"] == "networkx"


def test_admin_protocol_runtime_checkable() -> None:
    """A bare object lacking the methods does not satisfy the Protocol."""
    class Empty:
        pass

    assert not isinstance(Empty(), KGAdminClient)
