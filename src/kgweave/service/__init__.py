# @summary
# Service layer: abstract KGService interface plus the default in-process
# BuilderKGService that wraps the migrated KnowledgeGraphBuilder and the
# configured graph backend.
# Exports: KGService, BuilderKGService, build_default_service
# @end-summary
"""Service-layer interface and default implementation."""

from kgweave.service.builder_service import BuilderKGService, build_default_service
from kgweave.service.facade import KGService

__all__ = ["KGService", "BuilderKGService", "build_default_service"]
