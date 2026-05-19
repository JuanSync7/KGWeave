"""Typed result models returned by the runner."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from knowledge_graph.schemas import Span

__all__ = ["NodeView", "EdgeView", "PathView", "QueryResult"]


class NodeView(BaseModel):
    """A flat, Pydantic-typed projection of one ``:Node`` row."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    category: str
    name: str | None
    source: str
    corpus: str
    origin_id: str | None
    span: Span | None
    payload: dict[str, Any] = Field(default_factory=dict)


class EdgeView(BaseModel):
    """An edge connecting two ``NodeView`` ids."""

    model_config = ConfigDict(frozen=True)

    src: str
    dst: str
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class PathView(BaseModel):
    """A sequence of nodes + edges as returned by a traversal."""

    nodes: list[NodeView] = Field(default_factory=list)
    edges: list[EdgeView] = Field(default_factory=list)


class QueryResult(BaseModel):
    """Uniform envelope returned by the runner for every intent kind."""

    intent_kind: str
    nodes: list[NodeView] = Field(default_factory=list)
    paths: list[PathView] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
