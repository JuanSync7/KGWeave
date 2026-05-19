"""Pydantic ``QueryIntent`` discriminated union.

The intent layer is the public, typed front door to the graph: a Pydantic
model the caller fills in, the compiler renders to a parameterized Cypher
string, and the runner executes against a :class:`KGStore`.

Four intent kinds:

* :class:`FilterIntent`       — single-table ``MATCH (n:Node) WHERE ...``.
* :class:`TraverseIntent`     — variable-length path from an anchor over
  a chosen subset of rel-types in a chosen direction.
* :class:`NeighborhoodIntent` — undirected, all-rel-types ball of radius
  ``r`` around an anchor.
* :class:`RawCypher`          — escape hatch; read-only-enforced.

Edge names are the exact uppercase rel-table names from the schema.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AnchorRef",
    "EdgeType",
    "Category",
    "FilterIntent",
    "TraverseIntent",
    "NeighborhoodIntent",
    "RawCypher",
    "QueryIntent",
    "ALL_EDGE_TYPES",
]


# ---------------------------------------------------------------- enums

EdgeType = Literal[
    "PARENT_OF",
    "CONTAINS",
    "DRIVES",
    "READS",
    "SENSITIVE_TO",
    "INSTANTIATES",
    "OF_MODULE",
    "CONNECTS",
    "PARAM_OVERRIDE",
    "CALLS",
    "HAS_PORT",
    "HAS_PARAM",
    "HAS_NET",
    "HAS_TYPEDEF",
    "HAS_ENUM_VALUE",
    "HAS_MODPORT",
    "HAS_FUNCTION",
    "HAS_GENERATE",
    "CONTAINS_BLOCK",
    "IN_ORIGIN",
    "HAS_PAYLOAD",
]


ALL_EDGE_TYPES: tuple[str, ...] = (
    "PARENT_OF",
    "CONTAINS",
    "DRIVES",
    "READS",
    "SENSITIVE_TO",
    "INSTANTIATES",
    "OF_MODULE",
    "CONNECTS",
    "PARAM_OVERRIDE",
    "CALLS",
    "HAS_PORT",
    "HAS_PARAM",
    "HAS_NET",
    "HAS_TYPEDEF",
    "HAS_ENUM_VALUE",
    "HAS_MODPORT",
    "HAS_FUNCTION",
    "HAS_GENERATE",
    "CONTAINS_BLOCK",
    "IN_ORIGIN",
    "HAS_PAYLOAD",
)


Category = Literal[
    "semantic",
    "structural",
    "blob",
    "token",
    "directive",
    "unresolved",
]


# --------------------------------------------------------------- anchors


class AnchorRef(BaseModel):
    """How to resolve the start node of a traversal/neighborhood query.

    Exactly one of ``id`` or ``by_kind_name`` must be set.
    """

    model_config = ConfigDict(frozen=True)

    id: str | None = None
    by_kind_name: tuple[str, str] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "AnchorRef":
        set_count = (self.id is not None) + (self.by_kind_name is not None)
        if set_count != 1:
            raise ValueError(
                "AnchorRef requires exactly one of 'id' or 'by_kind_name'"
            )
        return self


# --------------------------------------------------------------- intents


class FilterIntent(BaseModel):
    """Single-table filter over ``:Node``."""

    kind: Literal["filter"] = "filter"
    node_kind: str | None = None
    category: Category | None = None
    name: str | None = None
    source: str | None = None
    corpus: str | None = None
    origin_id: str | None = None
    limit: int = Field(default=100, ge=1, le=10_000)


class TraverseIntent(BaseModel):
    """Variable-length traversal from an anchor over a rel-type subset."""

    kind: Literal["traverse"] = "traverse"
    anchor: AnchorRef
    via: list[EdgeType] = Field(min_length=1)
    direction: Literal["fwd", "rev", "both"] = "fwd"
    depth: int = Field(default=1, ge=1, le=8)
    limit: int = Field(default=200, ge=1, le=10_000)


class NeighborhoodIntent(BaseModel):
    """Undirected ball of radius ``r`` over **all** rel-types."""

    kind: Literal["neighborhood"] = "neighborhood"
    anchor: AnchorRef
    radius: int = Field(default=2, ge=1, le=4)
    limit: int = Field(default=500, ge=1, le=10_000)


class RawCypher(BaseModel):
    """Read-only escape hatch. Enforcement lives in ``readonly.py``."""

    kind: Literal["raw"] = "raw"
    cypher: str
    parameters: dict[str, Any] = Field(default_factory=dict)


QueryIntent = Annotated[
    Union[FilterIntent, TraverseIntent, NeighborhoodIntent, RawCypher],
    Field(discriminator="kind"),
]
