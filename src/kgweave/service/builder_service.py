# @summary
# Concrete KGService backed by the in-process KnowledgeGraphBuilder.
# Bridges the worker activity layer (Pydantic contracts) to the migrated
# knowledge_graph package. delete_by_source dispatches to the configured
# graph backend (NetworkX/Neo4j), which is a separate store maintained by
# the post-ingest pipeline; this matches RagWeave's prior layering.
# Exports: BuilderKGService, build_default_service
# Deps: kgweave.contracts, kgweave.service.facade,
#       kgweave.knowledge_graph (get_graph_backend),
#       kgweave.core.knowledge_graph (KnowledgeGraphBuilder),
#       kgweave.knowledge_graph.ingest_client
# @end-summary
"""Concrete ``KGService`` wired to the migrated KG implementation."""

from __future__ import annotations

import logging
from typing import Any, Optional

from kgweave.contracts import KGIngestRequest, KGIngestResult
from kgweave.service.facade import KGService

logger = logging.getLogger("kgweave.service.builder_service")


class BuilderKGService(KGService):
    """In-process KG service: ``KnowledgeGraphBuilder`` for ingest, optional
    backend for source-key deletion and health probes."""

    def __init__(
        self,
        builder: Any,
        ingest_client: Any,
        backend: Optional[Any] = None,
    ) -> None:
        self._builder = builder
        self._ingest = ingest_client
        self._backend = backend

    def extract_and_commit(self, request: KGIngestRequest) -> KGIngestResult:
        result = self._ingest.extract_and_commit(
            source_key=request.source_key,
            clean_text=request.clean_text,
            meta=dict(request.meta) if request.meta else None,
        )
        return KGIngestResult(
            source_key=result.source_key,
            entities_added=int(result.entities_added),
            triples_added=int(result.triples_added),
            chunks_processed=int(result.chunks_processed),
            elapsed_ms=float(result.elapsed_ms),
        )

    def delete_by_source(self, source_key: str) -> dict[str, int]:
        if self._backend is None:
            return {}
        stats = self._backend.remove_by_source(source_key)
        if hasattr(stats, "__dict__"):
            return {
                k: int(v) for k, v in vars(stats).items()
                if isinstance(v, (int, float))
            }
        if isinstance(stats, dict):
            return {k: int(v) for k, v in stats.items() if isinstance(v, (int, float))}
        return {}

    def health(self) -> dict[str, object]:
        info: dict[str, object] = {
            "ok": True,
            "builder_nodes": int(self._builder.graph.number_of_nodes()),
            "builder_edges": int(self._builder.graph.number_of_edges()),
        }
        if self._backend is not None:
            try:
                info["backend_stats"] = dict(self._backend.stats() or {})
            except Exception as exc:
                info["backend_error"] = str(exc)
        return info


def build_default_service(
    *, use_gliner: bool = False, with_backend: bool = True,
) -> BuilderKGService:
    """Construct a ``BuilderKGService`` with the default builder + backend.

    Args:
        use_gliner: Forwarded to :class:`KnowledgeGraphBuilder` (GLiNER vs regex).
        with_backend: If True, also load the configured graph backend so
            ``delete_by_source`` and ``health`` see the post-ingest store.
    """
    from kgweave.core.knowledge_graph import KnowledgeGraphBuilder
    from kgweave.knowledge_graph.ingest_client import KGBuilderIngestClient

    builder = KnowledgeGraphBuilder(use_gliner=use_gliner)
    ingest_client = KGBuilderIngestClient(builder)

    backend = None
    if with_backend:
        try:
            from kgweave.knowledge_graph import get_graph_backend
            backend = get_graph_backend()
        except Exception as exc:  # pragma: no cover — env-dependent
            logger.warning("graph backend unavailable: %s", exc)

    logger.info(
        "BuilderKGService ready use_gliner=%s with_backend=%s",
        use_gliner, backend is not None,
    )
    return BuilderKGService(
        builder=builder, ingest_client=ingest_client, backend=backend,
    )
