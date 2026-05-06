# @summary
# KGService — abstract facade the Temporal worker activities call into.
# Decouples the worker (Temporal-aware) from the concrete KG implementation
# (NetworkX/Neo4j/etc.). The migrated knowledge_graph package will provide
# a concrete subclass after Step 12.
# Exports: KGService
# Deps: abc, kgweave.contracts
# @end-summary
"""Abstract KG service facade — implementation-agnostic worker contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from kgweave.contracts import KGIngestRequest, KGIngestResult


class KGService(ABC):
    """Worker-facing service interface.

    Subclasses wrap the concrete KG backend (NetworkX, Neo4j, …). The
    Temporal worker is decoupled from that choice — it only sees this
    interface and the Pydantic contract types.
    """

    @abstractmethod
    def extract_and_commit(self, request: KGIngestRequest) -> KGIngestResult:
        """Phase 2b ingest: extract entities/relations and commit to the graph."""

    @abstractmethod
    def delete_by_source(self, source_key: str) -> dict[str, int]:
        """Source-key targeted deletion. Returns removal stats."""

    @abstractmethod
    def health(self) -> dict[str, object]:
        """Backend stats / health probe."""
