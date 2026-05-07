# @summary
# Regression net for the divergent-graph fix (Option B). Asserts that data
# written by BuilderKGService.extract_and_commit is visible to the same
# service's query path (DefaultKGQueryService reads via get_graph_backend()).
# Prior to the fix, ingest mutated an in-memory KnowledgeGraphBuilder.graph
# while queries read from a separate GraphStorageBackend instance — the two
# never synced, so retrieval returned stale or empty results.
# Exports: (test module)
# Deps: pytest, kgweave.service.builder_service,
#       kgweave.knowledge_graph.backends.NetworkXBackend
# @end-summary
"""End-to-end convergence: ingest writes must be visible to backend reads."""

from __future__ import annotations

import pytest

from kgweave.contracts import KGIngestRequest
from kgweave.knowledge_graph.backends import NetworkXBackend
from kgweave.service.builder_service import BuilderKGService


@pytest.fixture
def fresh_backend() -> NetworkXBackend:
    """Empty in-memory NetworkX backend (no on-disk load)."""
    return NetworkXBackend()


@pytest.fixture
def service(fresh_backend: NetworkXBackend) -> BuilderKGService:
    """Service whose ingest path writes to ``fresh_backend``.

    We do NOT use ``build_default_service`` because that loads the
    process-wide singleton; the convergence test needs a known-empty
    backend that we can inspect deterministically.
    """
    from kgweave.knowledge_graph.ingest_client import BackendIngestClient

    return BuilderKGService(
        ingest_client=BackendIngestClient(fresh_backend),
        backend=fresh_backend,
    )


def test_ingested_entities_are_visible_in_backend(
    service: BuilderKGService,
    fresh_backend: NetworkXBackend,
) -> None:
    """The graph backend (which queries read from) must reflect ingest writes."""
    text = "The CPU is connected to the memory bus and the GPU."
    result = service.extract_and_commit(
        KGIngestRequest(source_key="conv-1", clean_text=text, meta={}, trace_id=""),
    )

    # Ingest claims it added entities — those must appear in the backend.
    assert result.entities_added > 0, "ingest reported zero entities — fixture is broken"
    backend_entities = fresh_backend.get_all_entities()
    assert len(backend_entities) > 0, (
        "ingest wrote entities but backend.get_all_entities() returned empty — "
        "ingest path and query path are reading different graphs"
    )


def test_ingested_triples_are_visible_in_backend(
    service: BuilderKGService,
    fresh_backend: NetworkXBackend,
) -> None:
    """Triples added during ingest must be reachable through the backend stats."""
    text = "The CPU is connected to the GPU. The GPU drives the display."
    result = service.extract_and_commit(
        KGIngestRequest(source_key="conv-2", clean_text=text, meta={}, trace_id=""),
    )

    if result.triples_added == 0:
        pytest.skip("regex extractor produced no triples for this text")

    stats = fresh_backend.stats()
    assert int(stats.get("edges", 0)) > 0, (
        "ingest reported triples_added>0 but backend has zero edges — "
        "ingest is writing to a graph that queries cannot see"
    )


def test_source_key_is_recorded_on_backend_entities(
    service: BuilderKGService,
    fresh_backend: NetworkXBackend,
) -> None:
    """A query for the ingested source must find entities tagged with that key."""
    service.extract_and_commit(
        KGIngestRequest(
            source_key="tagged-source",
            clean_text="The CPU executes instructions for the operating system.",
            meta={},
            trace_id="",
        ),
    )
    count = fresh_backend.count_by_source_key("tagged-source")
    assert count > 0, (
        "no backend entities tagged with the ingested source_key — "
        "ingest writes are invisible to source-key queries"
    )
