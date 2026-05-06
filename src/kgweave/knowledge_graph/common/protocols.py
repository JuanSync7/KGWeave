# @summary
# Protocol contracts for KG dependencies that live outside the package.
# Keeps the KG subsystem free of direct imports from src.platform.* so the
# package can be extracted into KGWeave without code changes.
# Exports: LLMClient, set_default_llm_factory, get_default_llm,
#          KGAdminClient, KGIngestClient, KGIngestResult
# Deps: typing, dataclasses
# @end-summary
"""Dependency protocols for the knowledge graph package.

KG nodes that need an LLM either accept one via constructor injection or
resolve a process-wide default registered by the host application at boot
time. The host (RagWeave today, KGWeave standalone after extraction) calls
``set_default_llm_factory`` once during startup to bind a concrete provider.

This module never imports from ``src.platform`` — that boundary is what
makes the KG package portable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from kgweave.knowledge_graph.backend import RemovalStats

__all__ = [
    "LLMClient",
    "set_default_llm_factory",
    "get_default_llm",
    "clear_default_llm_factory",
    "KGAdminClient",
    "KGIngestClient",
    "KGIngestResult",
]


@runtime_checkable
class LLMClient(Protocol):
    """Minimal LLM surface used by KG extractors, matchers, and summarizers.

    Implementations only need to provide the methods the KG actually calls.
    RagWeave's ``LLMProvider`` satisfies this protocol structurally; tests
    can supply a stub.
    """

    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        model_alias: str = ...,
        temperature: Optional[float] = ...,
        max_tokens: Optional[int] = ...,
        **kwargs: Any,
    ) -> Any:
        """Return a chat-completion response for *messages*."""
        ...

    def json_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        model_alias: str = ...,
        temperature: Optional[float] = ...,
        max_tokens: Optional[int] = ...,
        **kwargs: Any,
    ) -> Any:
        """Return a JSON-mode completion for *messages*."""
        ...


_default_factory: Optional[Callable[[], LLMClient]] = None


def set_default_llm_factory(factory: Callable[[], LLMClient]) -> None:
    """Register a zero-arg factory that returns the default LLM client.

    Called once by the host application at startup. Idempotent — later calls
    overwrite the registration.
    """
    global _default_factory
    _default_factory = factory


def clear_default_llm_factory() -> None:
    """Remove any registered default factory. Primarily for tests."""
    global _default_factory
    _default_factory = None


def get_default_llm() -> LLMClient:
    """Return the host-registered default LLM client.

    Raises:
        RuntimeError: when no factory has been registered. Callers that want
            graceful degradation should accept ``llm_provider`` via their
            constructor instead of relying on this default.
    """
    if _default_factory is None:
        raise RuntimeError(
            "No LLM client configured for the knowledge_graph package. "
            "Pass llm_provider=... explicitly, or call "
            "kgweave.knowledge_graph.common.protocols.set_default_llm_factory(...) "
            "during application startup."
        )
    return _default_factory()


# ---------------------------------------------------------------------------
# KGAdminClient — lifecycle/admin contract (Step 4)
# ---------------------------------------------------------------------------


@runtime_checkable
class KGAdminClient(Protocol):
    """Lifecycle/admin surface used by ingest GC and migration code.

    Implemented by ``GraphStorageBackend`` (default methods) and by any
    out-of-process facade KGWeave will eventually expose. Lifecycle modules
    depend on this Protocol instead of the concrete backend class so that
    swapping in a remote KG service requires no code changes outside the
    wiring layer.
    """

    def count_by_source_key(self, source_key: str) -> int:
        """Return the number of entities currently tagged with *source_key*."""
        ...

    def delete_by_source_key(self, source_key: str) -> "RemovalStats":
        """Remove all data tied to *source_key* and return removal stats."""
        ...

    def health(self) -> Dict[str, object]:
        """Return a diagnostics dict (must include ``nodes``, ``edges``, ``backend``)."""
        ...


# ---------------------------------------------------------------------------
# KGIngestClient — ingest entry point (Step 5)
# ---------------------------------------------------------------------------


@dataclass
class KGIngestResult:
    """Outcome of a single ``extract_and_commit`` call.

    Attributes:
        source_key: Document key that was ingested.
        entities_added: Net new entities created (existing entities reused are
            counted as 0). Approximate when the backend cannot distinguish.
        triples_added: Net new triples written.
        chunks_processed: Number of chunks the ingest split *clean_text* into.
        elapsed_ms: Wall-clock time spent inside ``extract_and_commit``.
    """

    source_key: str
    entities_added: int = 0
    triples_added: int = 0
    chunks_processed: int = 0
    elapsed_ms: float = 0.0


@runtime_checkable
class KGIngestClient(Protocol):
    """Ingest entry point — collapses extraction + commit into one call.

    Replaces the two embedding-LangGraph nodes
    (``knowledge_graph_extraction``, ``knowledge_graph_storage``) plus the
    commit-time replay. Phase 2b consumers of ``CleanDocumentStore`` call
    this directly.
    """

    def extract_and_commit(
        self,
        source_key: str,
        clean_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> KGIngestResult:
        """Extract entities/relations from *clean_text* and commit to the KG."""
        ...
