# @summary
# Pydantic v2 request/response schemas for the KGWeave HTTP API (Step C).
# These models mirror the in-process kgweave.knowledge_graph surface used
# by retrieval consumers, but expose only read-side query operations. The
# contract here is the network boundary — wire compatibility is gated by
# CONTRACT_VERSION in kgweave.contracts.constants.
# Exports: ExpandRequest, ExpandResponse, TermMatchRequest, TermMatchResponse,
#          EntityResponse, PathRequest, PathHopModel, PathResultModel,
#          PathResponse, HealthResponse, ErrorResponse
# Deps: pydantic
# @end-summary
"""HTTP wire schemas for the KGWeave read-side API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# /v1/health
# ---------------------------------------------------------------------------


class HealthResponse(_Frozen):
    """Liveness + backend snapshot."""

    ok: bool
    contract_version: str
    backend: str
    stats: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# /v1/expand
# ---------------------------------------------------------------------------


class ExpandRequest(_Frozen):
    """Graph query expansion request."""

    query: str = Field(..., min_length=1)
    depth: Optional[int] = Field(None, ge=1, le=10)


class ExpandResponse(_Frozen):
    terms: list[str] = Field(default_factory=list)
    graph_context: str = ""


# ---------------------------------------------------------------------------
# /v1/term-index/match
# ---------------------------------------------------------------------------


class TermMatchRequest(_Frozen):
    """Word-level vocabulary lookup against the cached term index."""

    words: list[str] = Field(..., min_length=1)


class TermMatchResponse(_Frozen):
    matches: dict[str, list[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# /v1/term-index/query — query-level match with fallback
# ---------------------------------------------------------------------------


class KGQueryMatchRequest(_Frozen):
    """Match KG terms against a free-form query string.

    The server tokenises the query, runs the word-level lookup, and falls
    back to the top-N most-mentioned terms when no word produced a match.
    """

    query: str = Field(..., min_length=1)
    max_terms: int = Field(20, ge=1, le=200)
    min_word_length: int = Field(3, ge=1, le=20)


class KGQueryMatchResponse(_Frozen):
    matched: list[str] = Field(default_factory=list)
    used_fallback: bool = False


# ---------------------------------------------------------------------------
# /v1/entities/{key}
# ---------------------------------------------------------------------------


class EntityResponse(_Frozen):
    """Single entity probe result."""

    name: str
    type: str
    mention_count: int = Field(0, ge=0)
    sources: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# /v1/paths
# ---------------------------------------------------------------------------


class PathRequest(_Frozen):
    seed_entity: str = Field(..., min_length=1)
    patterns: list[list[str]] = Field(..., min_length=1)


class PathHopModel(_Frozen):
    from_entity: str
    edge_type: str
    to_entity: str


class PathResultModel(_Frozen):
    pattern_label: str
    seed_entity: str
    terminal_entity: str
    hops: list[PathHopModel]


class PathResponse(_Frozen):
    results: list[PathResultModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ErrorResponse(_Frozen):
    """Uniform error envelope returned by the API for non-2xx responses."""

    error: str
    detail: Optional[str] = None
