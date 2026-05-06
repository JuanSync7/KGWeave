# @summary
# Default KGIngestClient implementation that adapts KnowledgeGraphBuilder
# into the Protocol's extract_and_commit entry point. Single entry point
# replaces the embedding-LangGraph pair (extraction + storage) for Phase 2b
# consumers reading from CleanDocumentStore.
# Exports: KGBuilderIngestClient
# Deps: src.core.knowledge_graph, src.knowledge_graph.common.protocols
# @end-summary
"""Default ``KGIngestClient`` adapter over ``KnowledgeGraphBuilder``.

The adapter records pre/post graph sizes to compute net entity and triple
deltas. It is the in-process implementation; remote KG services will provide
their own ``KGIngestClient`` over the network without RagWeave changes.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from kgweave.core.knowledge_graph import KnowledgeGraphBuilder
from kgweave.knowledge_graph.common.protocols import KGIngestClient, KGIngestResult

logger = logging.getLogger("rag.knowledge_graph.ingest_client")

__all__ = ["KGBuilderIngestClient"]


class KGBuilderIngestClient:
    """Adapt a :class:`KnowledgeGraphBuilder` to the ``KGIngestClient`` Protocol.

    Each ``extract_and_commit`` call invokes ``builder.add_chunk`` once for
    the supplied *clean_text* and reports net node/edge deltas. The builder
    handles entity extraction, alias resolution, and edge insertion.
    """

    def __init__(self, builder: KnowledgeGraphBuilder) -> None:
        self._builder = builder

    def extract_and_commit(
        self,
        source_key: str,
        clean_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> KGIngestResult:
        """Extract entities/relations from *clean_text* and commit to the graph.

        Args:
            source_key: Document key tagged onto every entity/edge added.
            clean_text: Cleaned document text. Empty strings are a no-op.
            meta: Optional metadata (trace_id, source_name). Currently unused
                by the in-process adapter; reserved for remote implementations.

        Returns:
            ``KGIngestResult`` with net entity/triple counts and elapsed time.
        """
        t0 = time.monotonic()

        if not clean_text:
            return KGIngestResult(
                source_key=source_key,
                chunks_processed=0,
                elapsed_ms=(time.monotonic() - t0) * 1000.0,
            )

        nodes_before = self._builder.graph.number_of_nodes()
        edges_before = self._builder.graph.number_of_edges()

        self._builder.add_chunk(clean_text, source=source_key)

        nodes_after = self._builder.graph.number_of_nodes()
        edges_after = self._builder.graph.number_of_edges()
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        result = KGIngestResult(
            source_key=source_key,
            entities_added=nodes_after - nodes_before,
            triples_added=edges_after - edges_before,
            chunks_processed=1,
            elapsed_ms=elapsed_ms,
        )
        logger.debug(
            "extract_and_commit source_key=%s entities=+%d triples=+%d elapsed_ms=%.1f",
            source_key,
            result.entities_added,
            result.triples_added,
            elapsed_ms,
        )
        return result
