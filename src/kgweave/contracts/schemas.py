# @summary
# Pydantic v2 schemas for the KGWeave Temporal wire contract.
# Failures are signalled by ApplicationError raised in the worker; the
# error's ``type`` field carries one of the KGErrorClass values so the
# RagWeave workflow can decide retry vs. permanent.
# Exports: KGIngestRequest, KGIngestResult, KGAdminRequest, KGAdminResult,
#          KGErrorClass
# Deps: pydantic
# @end-summary
"""Pydantic schemas for the KGWeave Temporal wire contract."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KGErrorClass = Literal["transient", "document", "system"]
"""Failure taxonomy used by the workflow to decide retry policy:

* ``transient`` — LLM rate limit, network blip, OOM. Retry with backoff.
* ``document``  — content the extractor cannot handle. Mark permanent;
  surface for human review.
* ``system``    — code/config bug, missing model. Halt retries.
"""


class KGIngestRequest(BaseModel):
    """Phase 2b ingest request payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_key: str = Field(..., min_length=1)
    clean_text: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None


class KGIngestResult(BaseModel):
    """Successful Phase 2b ingest result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_key: str = Field(..., min_length=1)
    entities_added: int = Field(0, ge=0)
    triples_added: int = Field(0, ge=0)
    chunks_processed: int = Field(0, ge=0)
    elapsed_ms: float = Field(0.0, ge=0.0)


class KGAdminRequest(BaseModel):
    """Admin/lifecycle activity request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["delete_by_source", "health"]
    source_key: Optional[str] = None

    @field_validator("source_key")
    @classmethod
    def _strip_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def _delete_requires_source_key(self) -> "KGAdminRequest":
        if self.op == "delete_by_source" and not self.source_key:
            raise ValueError("delete_by_source requires source_key")
        return self


class KGAdminResult(BaseModel):
    """Admin/lifecycle activity result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    stats: dict[str, Any] = Field(default_factory=dict)
