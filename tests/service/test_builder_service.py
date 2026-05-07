# @summary
# Smoke tests for BuilderKGService — verifies the migrated KG package
# is wired correctly to the Pydantic contract layer used by the worker.
# Deps: pytest, kgweave.contracts, kgweave.service.builder_service
# @end-summary
"""Smoke tests for the concrete BuilderKGService."""

from __future__ import annotations

import pytest

from kgweave.contracts import KGIngestRequest, KGIngestResult
from kgweave.service.builder_service import BuilderKGService, build_default_service


@pytest.fixture
def service() -> BuilderKGService:
    # Skip backend wiring — env-dependent (Neo4j / graph file paths).
    return build_default_service(with_backend=False)


def test_extract_and_commit_returns_contract_result(service: BuilderKGService) -> None:
    req = KGIngestRequest(
        source_key="doc1.md",
        clean_text="Alice works at Acme Corp. Bob also works at Acme Corp.",
    )
    result = service.extract_and_commit(req)
    assert isinstance(result, KGIngestResult)
    assert result.source_key == "doc1.md"
    assert result.chunks_processed == 1
    assert result.entities_added >= 0
    assert result.elapsed_ms >= 0.0


def test_extract_and_commit_empty_text_is_noop(service: BuilderKGService) -> None:
    result = service.extract_and_commit(
        KGIngestRequest(source_key="empty.md", clean_text="")
    )
    assert result.source_key == "empty.md"
    assert result.chunks_processed == 0
    assert result.entities_added == 0
    assert result.triples_added == 0


def test_health_reports_backend_counts(service: BuilderKGService) -> None:
    info = service.health()
    assert info["ok"] is True
    # Backend-native service surfaces backend stats; legacy builder_* keys
    # only appear when an explicit KnowledgeGraphBuilder is supplied.
    assert "nodes" in info
    assert "edges" in info
    assert "backend_stats" in info


def test_delete_by_source_returns_zero_stats_for_empty_backend(
    service: BuilderKGService,
) -> None:
    """build_default_service now always supplies a backend (in-memory fallback
    when the configured one is unavailable), so delete_by_source returns the
    backend's RemovalStats — zero counts for an empty graph, not ``{}``."""
    stats = service.delete_by_source("doc1.md")
    assert stats == {
        "entities_pruned": 0,
        "entities_removed": 0,
        "triples_removed": 0,
    }


def test_delete_by_source_returns_empty_when_backend_explicitly_none() -> None:
    """The legacy contract — ``{}`` when no backend — is preserved when a
    caller constructs the service directly without one."""
    from kgweave.knowledge_graph.ingest_client import BackendIngestClient
    from kgweave.knowledge_graph.backends import NetworkXBackend

    backend = NetworkXBackend()
    svc = BuilderKGService(
        ingest_client=BackendIngestClient(backend),
        backend=None,
    )
    assert svc.delete_by_source("doc1.md") == {}
