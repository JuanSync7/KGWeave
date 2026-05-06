"""Query sub-package for the KG subsystem.

Contains entity matching, query expansion, sanitization, and path-pattern
traversal logic.
"""

from kgweave.knowledge_graph.query.context_formatter import GraphContextFormatter
from kgweave.knowledge_graph.query.entity_matcher import EntityMatcher
from kgweave.knowledge_graph.query.expander import GraphQueryExpander
from kgweave.knowledge_graph.query.path_matcher import PathMatcher
from kgweave.knowledge_graph.query.sanitizer import QuerySanitizer
from kgweave.knowledge_graph.query.schemas import ExpansionResult, PathHop, PathResult
from kgweave.knowledge_graph.query.term_index import (
    KGTermIndex,
    clear_term_index_cache,
    get_term_index,
)

__all__ = [
    "EntityMatcher",
    "ExpansionResult",
    "GraphContextFormatter",
    "GraphQueryExpander",
    "KGTermIndex",
    "PathHop",
    "PathMatcher",
    "PathResult",
    "QuerySanitizer",
    "clear_term_index_cache",
    "get_term_index",
]
