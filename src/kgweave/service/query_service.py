# @summary
# Read-side query service: abstract interface used by the HTTP API and any
# other read consumer. Decouples transport (FastAPI / future gRPC / direct
# in-process call) from the underlying knowledge_graph package.
# Exports: KGQueryService, EntityNotFound, DefaultKGQueryService,
#          build_default_query_service
# Deps: abc, kgweave.contracts.http, kgweave.knowledge_graph
# @end-summary
"""Abstract read-side KG service plus default in-process implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from kgweave.contracts.http import (
    EntityResponse,
    ExpandResponse,
    HealthResponse,
    KGQueryMatchResponse,
    PathHopModel,
    PathResponse,
    PathResultModel,
    TermMatchResponse,
)

logger = logging.getLogger("kgweave.service.query")


class EntityNotFound(LookupError):
    """Raised when a requested entity key has no record in the graph."""


class KGQueryService(ABC):
    """Read-side service interface used by the HTTP API and clients.

    Subclasses adapt the underlying graph (in-process backend, remote HTTP,
    a fixture for tests) to a uniform read surface. All methods consume and
    return Pydantic wire models so transports can serialize directly.
    """

    @abstractmethod
    def health(self) -> HealthResponse:
        """Liveness probe + backend stats."""

    @abstractmethod
    def expand(self, query: str, depth: Optional[int] = None) -> ExpandResponse:
        """Graph query expansion."""

    @abstractmethod
    def match_terms(self, words: list[str]) -> TermMatchResponse:
        """Word-level lookup against the cached term index."""

    @abstractmethod
    def match_kg_query(
        self,
        query: str,
        max_terms: int = 20,
        min_word_length: int = 3,
    ) -> KGQueryMatchResponse:
        """Match KG terms against a free-form query, with top-N fallback.

        Tokenises the query, runs a word-level lookup, and falls back to the
        top-N most-mentioned terms when no word matched. ``used_fallback``
        in the response distinguishes the two paths so callers can adjust
        downstream prompting if needed.
        """

    @abstractmethod
    def get_entity(self, key: str) -> EntityResponse:
        """Single entity probe. Raises ``EntityNotFound`` if missing."""

    @abstractmethod
    def find_paths(
        self, seed_entity: str, patterns: list[list[str]]
    ) -> PathResponse:
        """Multi-hop path-pattern evaluation."""


class DefaultKGQueryService(KGQueryService):
    """Default in-process implementation backed by ``kgweave.knowledge_graph``.

    Lazy-imports the package on first call so building this service does not
    pull in heavy optional deps (gliner, leidenalg) unless they are used.
    """

    def __init__(self) -> None:
        self._backend = None
        self._expander = None
        self._path_matcher = None

    # ------------------------------------------------------------------
    # Lazy resolvers
    # ------------------------------------------------------------------

    def _get_backend(self):
        if self._backend is None:
            from kgweave.knowledge_graph import get_graph_backend  # noqa: PLC0415

            self._backend = get_graph_backend()
        return self._backend

    def _get_expander(self):
        if self._expander is None:
            from kgweave.knowledge_graph import get_query_expander  # noqa: PLC0415

            self._expander = get_query_expander(backend=self._get_backend())
        return self._expander

    def _get_path_matcher(self):
        if self._path_matcher is None:
            from kgweave.knowledge_graph.query.path_matcher import (  # noqa: PLC0415
                PathMatcher,
            )

            self._path_matcher = PathMatcher(backend=self._get_backend())
        return self._path_matcher

    # ------------------------------------------------------------------
    # KGQueryService implementation
    # ------------------------------------------------------------------

    def health(self) -> HealthResponse:
        from kgweave.contracts import CONTRACT_VERSION  # noqa: PLC0415

        backend_name = "unknown"
        stats: dict[str, object] = {}
        try:
            backend = self._get_backend()
            backend_name = type(backend).__name__
            stats = dict(backend.stats())
            ok = True
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("health probe backend unavailable: %s", exc)
            ok = False
        return HealthResponse(
            ok=ok,
            contract_version=CONTRACT_VERSION,
            backend=backend_name,
            stats=stats,
        )

    def expand(self, query: str, depth: Optional[int] = None) -> ExpandResponse:
        result = self._get_expander().expand(query, depth=depth)
        return ExpandResponse(
            terms=list(result.terms),
            graph_context=getattr(result, "graph_context", "") or "",
        )

    def match_terms(self, words: list[str]) -> TermMatchResponse:
        from kgweave.knowledge_graph import get_term_index  # noqa: PLC0415

        index = get_term_index()
        matches: dict[str, list[str]] = {}
        for word in words:
            key = word.lower()
            hits = index.word_index.get(key, [])
            if hits:
                matches[word] = list(hits)
        return TermMatchResponse(matches=matches)

    def match_kg_query(
        self,
        query: str,
        max_terms: int = 20,
        min_word_length: int = 3,
    ) -> KGQueryMatchResponse:
        from kgweave.knowledge_graph import get_term_index  # noqa: PLC0415

        index = get_term_index()
        if not index.terms:
            return KGQueryMatchResponse(matched=[], used_fallback=False)

        query_words = {
            w.lower() for w in query.split() if len(w) >= min_word_length
        }
        seen: set[str] = set()
        matched: list[str] = []
        for word in query_words:
            for term in index.word_index.get(word, []):
                if term not in seen:
                    seen.add(term)
                    matched.append(term)
                    if len(matched) >= max_terms:
                        break
            if len(matched) >= max_terms:
                break

        if matched:
            return KGQueryMatchResponse(matched=matched, used_fallback=False)
        return KGQueryMatchResponse(
            matched=list(index.terms[:max_terms]),
            used_fallback=True,
        )

    def get_entity(self, key: str) -> EntityResponse:
        backend = self._get_backend()
        entity = backend.get_entity(key)
        if entity is None:
            raise EntityNotFound(key)
        return EntityResponse(
            name=entity.name,
            type=entity.type,
            mention_count=getattr(entity, "mention_count", 0),
            sources=list(getattr(entity, "sources", [])),
            aliases=list(getattr(entity, "aliases", [])),
            summary=getattr(entity, "current_summary", "") or "",
        )

    def find_paths(
        self, seed_entity: str, patterns: list[list[str]]
    ) -> PathResponse:
        matcher = self._get_path_matcher()
        results = matcher.evaluate(seed_entity, patterns)
        return PathResponse(
            results=[
                PathResultModel(
                    pattern_label=pr.pattern_label,
                    seed_entity=pr.seed_entity,
                    terminal_entity=pr.terminal_entity,
                    hops=[
                        PathHopModel(
                            from_entity=hop.from_entity,
                            edge_type=hop.edge_type,
                            to_entity=hop.to_entity,
                        )
                        for hop in pr.hops
                    ],
                )
                for pr in results
            ]
        )


def build_default_query_service() -> KGQueryService:
    """Construct the default in-process query service."""
    return DefaultKGQueryService()
