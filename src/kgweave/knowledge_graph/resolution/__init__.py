"""Entity resolution sub-package for the KG subsystem.

Provides embedding-based and alias-table-based entity deduplication.
"""

from kgweave.knowledge_graph.resolution.schemas import MergeCandidate, ResolutionReport
from kgweave.knowledge_graph.resolution.resolver import EntityResolver

__all__ = ["EntityResolver", "MergeCandidate", "ResolutionReport"]
