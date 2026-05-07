# @summary
# Default KGIngestClient implementations. BackendIngestClient writes ingest
# results directly to the configured GraphStorageBackend — the same backend
# instance that DefaultKGQueryService reads from — so ingested data is
# immediately visible to retrieval. KGBuilderIngestClient is the legacy
# in-memory adapter retained for tests that pin to the old behavior; it
# writes only to KnowledgeGraphBuilder.graph and is **not** used by the
# default service wiring.
# Exports: BackendIngestClient, KGBuilderIngestClient
# Deps: kgweave.core.knowledge_graph (legacy), kgweave.knowledge_graph.backend,
#       kgweave.knowledge_graph.extraction (RegexEntityExtractor / GLiNER),
#       kgweave.knowledge_graph.common.protocols
# @end-summary
"""KGIngestClient implementations.

The backend-native client (``BackendIngestClient``) is the production path:
it extracts entities/triples via the package extractor and upserts them into
the same ``GraphStorageBackend`` instance the query service reads from. This
is the fix for the divergence between ingest writes (going to a separate
in-memory ``KnowledgeGraphBuilder.graph``) and query reads (hitting the
backend) that previously caused silent retrieval misses.

The legacy ``KGBuilderIngestClient`` is preserved for tests and offline
benchmark scripts that explicitly want the in-memory ``KnowledgeGraphBuilder``
behavior. It is NOT wired into ``build_default_service``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from kgweave.knowledge_graph.backend import GraphStorageBackend
from kgweave.knowledge_graph.common.protocols import KGIngestClient, KGIngestResult

logger = logging.getLogger("rag.knowledge_graph.ingest_client")

__all__ = ["BackendIngestClient", "KGBuilderIngestClient"]


def _make_default_extractor(use_gliner: bool):
    """Build the default package extractor (regex or GLiNER fallback).

    GLiNER falls back to regex internally when its model isn't available, so
    callers can pass ``use_gliner=True`` and still get a working extractor on
    machines without the GLiNER model installed.
    """
    if use_gliner:
        try:
            from kgweave.knowledge_graph.extraction.gliner_extractor import (
                GLiNEREntityExtractor,
            )
            return GLiNEREntityExtractor()
        except Exception as exc:
            logger.warning(
                "GLiNER unavailable (%s); falling back to RegexEntityExtractor.",
                exc,
            )
    from kgweave.knowledge_graph.extraction.regex_extractor import (
        RegexEntityExtractor,
    )
    return RegexEntityExtractor()


class BackendIngestClient:
    """KG ingest client that writes directly to a ``GraphStorageBackend``.

    This is the production ingest path. Entities and triples extracted from
    a chunk are upserted into the same backend instance the query service
    reads from, so ingest writes are immediately visible to retrieval.

    Args:
        backend: The graph backend to write to. Must be the same instance
            (or share underlying storage with) the one held by
            ``DefaultKGQueryService`` for queries to see the writes.
        extractor: An entity/triple extractor exposing ``extract(text, source)``
            → ``ExtractionResult``. When ``None``, a default
            :class:`RegexEntityExtractor` (or GLiNER if enabled) is built.
        use_gliner: Forwarded to the default extractor when *extractor* is
            ``None``. Ignored when *extractor* is supplied.
    """

    def __init__(
        self,
        backend: GraphStorageBackend,
        extractor: Optional[Any] = None,
        *,
        use_gliner: bool = False,
    ) -> None:
        self._backend = backend
        self._extractor = extractor or _make_default_extractor(use_gliner)

    def extract_and_commit(
        self,
        source_key: str,
        clean_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> KGIngestResult:
        """Extract entities/relations from *clean_text* and write to the backend.

        Args:
            source_key: Document key tagged onto every entity/edge added.
            clean_text: Cleaned document text. Empty input is a no-op.
            meta: Optional metadata (trace_id, source_name). Reserved for
                future remote implementations; the in-process backend client
                does not consume it today.

        Returns:
            ``KGIngestResult`` with net entity/triple counts (delta against
            backend stats before/after) and elapsed time.
        """
        t0 = time.monotonic()

        if not clean_text:
            return KGIngestResult(
                source_key=source_key,
                chunks_processed=0,
                elapsed_ms=(time.monotonic() - t0) * 1000.0,
            )

        stats_before = self._backend.stats()
        nodes_before = int(stats_before.get("nodes", 0))
        edges_before = int(stats_before.get("edges", 0))

        result = self._extractor.extract(clean_text, source=source_key)
        if result.entities:
            self._backend.upsert_entities(list(result.entities))
        if result.triples:
            self._backend.upsert_triples(list(result.triples))

        stats_after = self._backend.stats()
        nodes_after = int(stats_after.get("nodes", 0))
        edges_after = int(stats_after.get("edges", 0))
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        ingest_result = KGIngestResult(
            source_key=source_key,
            entities_added=nodes_after - nodes_before,
            triples_added=edges_after - edges_before,
            chunks_processed=1,
            elapsed_ms=elapsed_ms,
        )
        logger.debug(
            "BackendIngestClient.extract_and_commit source_key=%s "
            "entities=+%d triples=+%d elapsed_ms=%.1f",
            source_key,
            ingest_result.entities_added,
            ingest_result.triples_added,
            elapsed_ms,
        )
        return ingest_result


class KGBuilderIngestClient:
    """Legacy adapter over :class:`KnowledgeGraphBuilder` (in-memory only).

    Retained for tests and offline benchmarks that explicitly want the
    in-memory ``nx.DiGraph`` behavior. Production wiring goes through
    :class:`BackendIngestClient` so writes are visible to the query backend.
    """

    def __init__(self, builder: Any) -> None:
        self._builder = builder

    def extract_and_commit(
        self,
        source_key: str,
        clean_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> KGIngestResult:
        """Add *clean_text* to the in-memory builder graph and report deltas."""
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

        return KGIngestResult(
            source_key=source_key,
            entities_added=nodes_after - nodes_before,
            triples_added=edges_after - edges_before,
            chunks_processed=1,
            elapsed_ms=elapsed_ms,
        )
