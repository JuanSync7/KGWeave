# @summary
# Tests the KGIngestClient Protocol and the KGBuilderIngestClient default
# implementation that adapts KnowledgeGraphBuilder.add_chunk into a single
# extract_and_commit entry point.
# Exports: (test module)
# Deps: pytest, src.core.knowledge_graph, src.knowledge_graph.ingest_client,
#       src.knowledge_graph.common.protocols
# @end-summary
"""Step 5: KGIngestClient Protocol + default builder adapter."""

from __future__ import annotations

import pytest

from kgweave.core.knowledge_graph import KnowledgeGraphBuilder
from kgweave.knowledge_graph.common.protocols import KGIngestClient, KGIngestResult
from kgweave.knowledge_graph.ingest_client import KGBuilderIngestClient


@pytest.fixture
def builder() -> KnowledgeGraphBuilder:
    return KnowledgeGraphBuilder(use_gliner=False)


@pytest.fixture
def client(builder: KnowledgeGraphBuilder) -> KGBuilderIngestClient:
    return KGBuilderIngestClient(builder=builder)


def test_builder_client_satisfies_ingest_protocol(
    client: KGBuilderIngestClient,
) -> None:
    assert isinstance(client, KGIngestClient)


def test_extract_and_commit_returns_ingest_result(
    client: KGBuilderIngestClient,
) -> None:
    result = client.extract_and_commit(
        source_key="doc1.md",
        clean_text="The CPU executes instructions. The GPU handles graphics.",
    )
    assert isinstance(result, KGIngestResult)
    assert result.source_key == "doc1.md"
    assert result.chunks_processed >= 1
    assert result.elapsed_ms >= 0.0


def test_extract_and_commit_grows_graph(
    client: KGBuilderIngestClient,
    builder: KnowledgeGraphBuilder,
) -> None:
    nodes_before = builder.graph.number_of_nodes()
    result = client.extract_and_commit(
        source_key="doc2.md",
        clean_text="The CPU is connected to the memory bus and the GPU.",
    )
    nodes_after = builder.graph.number_of_nodes()
    assert nodes_after >= nodes_before
    assert result.entities_added == nodes_after - nodes_before


def test_extract_and_commit_tags_with_source_key(
    client: KGBuilderIngestClient,
    builder: KnowledgeGraphBuilder,
) -> None:
    client.extract_and_commit(
        source_key="tagged.md",
        clean_text="The CPU is connected to the GPU via the bus.",
    )
    sources_seen = set()
    for _, data in builder.graph.nodes(data=True):
        sources_seen.update(data.get("sources", []))
    assert "tagged.md" in sources_seen


def test_extract_and_commit_accepts_meta(
    client: KGBuilderIngestClient,
) -> None:
    result = client.extract_and_commit(
        source_key="m.md",
        clean_text="Voltage drops occur when current rises.",
        meta={"trace_id": "abc-123"},
    )
    assert result.source_key == "m.md"


def test_extract_and_commit_empty_text_is_safe(
    client: KGBuilderIngestClient,
) -> None:
    result = client.extract_and_commit(source_key="empty.md", clean_text="")
    assert result.entities_added == 0
    assert result.triples_added == 0
