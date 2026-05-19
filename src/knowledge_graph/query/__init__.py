"""Public query layer — Pydantic intents → parameterized Cypher → typed results.

See ``docs/plans/KUZU_PORT_PLAN.md`` Phase D for the contract. Out of
this package nothing should import sibling modules directly; re-exports
below are the stable surface.
"""

from __future__ import annotations

from knowledge_graph.query.compiler import compile_intent
from knowledge_graph.query.intents import (
    ALL_EDGE_TYPES,
    AnchorRef,
    EdgeType,
    FilterIntent,
    NeighborhoodIntent,
    QueryIntent,
    RawCypher,
    TraverseIntent,
)
from knowledge_graph.query.readonly import (
    BANNED_KEYWORDS,
    ReadOnlyViolation,
    assert_read_only,
)
from knowledge_graph.query.results import (
    EdgeView,
    NodeView,
    PathView,
    QueryResult,
)
from knowledge_graph.query.runner import AmbiguousAnchor, run_intent

__all__ = [
    "ALL_EDGE_TYPES",
    "AmbiguousAnchor",
    "AnchorRef",
    "BANNED_KEYWORDS",
    "EdgeType",
    "EdgeView",
    "FilterIntent",
    "NeighborhoodIntent",
    "NodeView",
    "PathView",
    "QueryIntent",
    "QueryResult",
    "RawCypher",
    "ReadOnlyViolation",
    "TraverseIntent",
    "assert_read_only",
    "compile_intent",
    "run_intent",
]
