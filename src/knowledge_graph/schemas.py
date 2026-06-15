"""Cross-builder Pydantic contracts for KGWeave.

Phase A introduces the minimum needed to round-trip source spans:

* ``Span``      — byte-offset + line/col location inside an origin.
* ``OriginRef`` — handle returned by ``KGStore.snapshot_file``.
* ``NodeRef``   — minimal node handle; populated by later phases.

The full schemas (``Path``, ``QueryResult`` etc.) land with Phase D.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Span(BaseModel):
    """Byte-precise location inside an ``:Origin``.

    Offsets are **bytes**, not characters — the canonical I3 guarantee.
    """

    model_config = ConfigDict(frozen=True)

    origin_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    start_line: int = Field(default=0, ge=0)
    end_line: int = Field(default=0, ge=0)
    start_col: int = Field(default=0, ge=0)
    end_col: int = Field(default=0, ge=0)

    def length(self) -> int:
        return self.end_offset - self.start_offset


class OriginRef(BaseModel):
    """Handle to a snapshotted file."""

    model_config = ConfigDict(frozen=True)

    id: str
    uri: str
    sha256: str
    source: str
    corpus: str


class NodeRef(BaseModel):
    """Minimal node handle (populated by Phase C)."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    source: str
    corpus: str
    origin_id: str | None = None


__all__ = ["Span", "OriginRef", "NodeRef"]
