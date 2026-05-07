# @summary
# Concrete KGService that ingests directly into the configured graph backend
# (NetworkX/Neo4j). Writes from extract_and_commit land in the same backend
# instance DefaultKGQueryService reads from, so retrieval sees ingested data.
# A legacy in-memory KnowledgeGraphBuilder may be passed in for tests or
# offline benchmarks; when present, health() reports its node/edge counts
# alongside the backend stats. New code should not pass a builder.
# Exports: BuilderKGService, build_default_service
# Deps: kgweave.contracts, kgweave.service.facade,
#       kgweave.knowledge_graph (get_graph_backend),
#       kgweave.knowledge_graph.ingest_client (BackendIngestClient)
# @end-summary
"""Concrete ``KGService`` writing through the configured graph backend."""

from __future__ import annotations

import logging
from typing import Any, Optional

from kgweave.contracts import KGIngestRequest, KGIngestResult
from kgweave.service.facade import KGService

logger = logging.getLogger("kgweave.service.builder_service")


class BuilderKGService(KGService):
    """Backend-native KG service.

    The ingest client is expected to write into the same ``GraphStorageBackend``
    instance held in ``self._backend``; that backend is also what the query
    service reads from, ensuring ingest/query convergence.

    Args:
        ingest_client: Object exposing ``extract_and_commit(source_key,
            clean_text, meta)``. In production this is
            :class:`BackendIngestClient`. Tests may pass a
            :class:`KGBuilderIngestClient` (legacy) — but in that case
            ingest writes will NOT be visible to the backend.
        backend: The graph backend the query service reads from. May be
            ``None`` only in narrow test scenarios; production wiring
            always supplies one.
        builder: Optional legacy ``KnowledgeGraphBuilder`` retained for
            health/diagnostic surfacing. Not used during ingest by the
            backend-native client.
    """

    def __init__(
        self,
        ingest_client: Any,
        backend: Optional[Any] = None,
        builder: Optional[Any] = None,
    ) -> None:
        self._ingest = ingest_client
        self._backend = backend
        self._builder = builder

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
        info: dict[str, object] = {"ok": True}
        if self._backend is not None:
            try:
                backend_stats = dict(self._backend.stats() or {})
                info["backend_stats"] = backend_stats
                info["nodes"] = int(backend_stats.get("nodes", 0))
                info["edges"] = int(backend_stats.get("edges", 0))
            except Exception as exc:
                info["backend_error"] = str(exc)
        if self._builder is not None:
            try:
                info["builder_nodes"] = int(self._builder.graph.number_of_nodes())
                info["builder_edges"] = int(self._builder.graph.number_of_edges())
            except Exception:
                pass
        return info


def build_default_service(
    *, use_gliner: bool = False, with_backend: bool = True,
) -> BuilderKGService:
    """Construct a ``BuilderKGService`` wired to the package backend.

    Ingest writes through :class:`BackendIngestClient` into the configured
    ``GraphStorageBackend`` (the same singleton the query service reads from).

    Args:
        use_gliner: Forwarded to the default extractor (GLiNER vs regex);
            GLiNER falls back to regex when its model isn't installed.
        with_backend: Must be True for ingest to function. Retained for
            backward compatibility with tests that previously toggled the
            backend off (those tests should be updated to pass an explicit
            backend or use the legacy ``KGBuilderIngestClient`` directly).
    """
    from kgweave.knowledge_graph.ingest_client import BackendIngestClient

    backend = None
    if with_backend:
        try:
            from kgweave.knowledge_graph import get_graph_backend
            backend = get_graph_backend()
        except Exception as exc:  # pragma: no cover — env-dependent
            logger.warning("graph backend unavailable: %s", exc)

    if backend is None:
        # Dev fallback: ingest still needs a target. Construct an in-memory
        # NetworkX backend so the worker doesn't crash, but this means the
        # graph is process-local — production must succeed in get_graph_backend.
        from kgweave.knowledge_graph.backends import NetworkXBackend
        backend = NetworkXBackend()
        logger.warning(
            "BuilderKGService falling back to in-memory NetworkXBackend; "
            "data will not persist across worker restarts."
        )

    ingest_client = BackendIngestClient(backend, use_gliner=use_gliner)

    logger.info(
        "BuilderKGService ready use_gliner=%s backend=%s",
        use_gliner, type(backend).__name__,
    )
    return BuilderKGService(ingest_client=ingest_client, backend=backend)
