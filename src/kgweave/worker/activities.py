# @summary
# Temporal activity defs for KGWeave. Each activity name matches the
# constant in the contract package so callers (RagWeave) dispatch by name
# without importing KGWeave code. Failures are converted to ApplicationError
# with type=KGErrorClass so the parent workflow can decide retry policy.
# Exports: kg_phase2b_activity, kg_delete_by_source_activity,
#          kg_health_activity, set_service
# Deps: temporalio.activity, temporalio.exceptions, kgweave.contracts,
#       kgweave.service
# @end-summary
"""Temporal activity defs for KGWeave's Phase 2b worker."""

from __future__ import annotations

import logging
from typing import Optional

from temporalio import activity
from temporalio.exceptions import ApplicationError

from kgweave.contracts import (
    KG_DELETE_BY_SOURCE_ACTIVITY,
    KG_HEALTH_ACTIVITY,
    KG_PHASE2B_ACTIVITY,
    KGAdminRequest,
    KGAdminResult,
    KGIngestRequest,
    KGIngestResult,
)
from kgweave.service import KGService

logger = logging.getLogger("kgweave.worker.activities")

# Process-wide service binding. set_service() is called by the worker entry
# point at startup; tests inject fakes via the same hook.
_service: Optional[KGService] = None


def set_service(service: KGService) -> None:
    """Bind the concrete KGService used by the activity defs."""
    global _service
    _service = service


def _require_service() -> KGService:
    if _service is None:
        raise ApplicationError(
            "KGService not configured — call kgweave.worker.set_service(...) "
            "during worker startup.",
            type="system",
            non_retryable=True,
        )
    return _service


def _classify_error(exc: BaseException) -> str:
    """Best-effort classification when the service did not raise an
    ApplicationError itself. Subclasses should prefer raising
    ``ApplicationError(type=...)`` directly so retry policy is explicit."""
    name = type(exc).__name__
    if name in {"FileNotFoundError", "ValueError", "ValidationError"}:
        return "document"
    if name in {"ImportError", "AttributeError", "KeyError", "TypeError"}:
        return "system"
    return "transient"


@activity.defn(name=KG_PHASE2B_ACTIVITY)
async def kg_phase2b_activity(request: KGIngestRequest) -> KGIngestResult:
    """Phase 2b ingest: extract + commit a single document to the KG.

    Failures are raised as :class:`ApplicationError` with ``type`` set to
    one of the :data:`~kgweave.contracts.KGErrorClass` values. The calling
    RagWeave workflow inspects ``type`` to decide retry vs. permanent.
    """
    svc = _require_service()
    try:
        return svc.extract_and_commit(request)
    except ApplicationError:
        raise
    except Exception as exc:
        klass = _classify_error(exc)
        logger.exception(
            "kg_phase2b failed source_key=%s class=%s",
            request.source_key, klass,
        )
        raise ApplicationError(
            f"kg_phase2b failed: {exc}",
            type=klass,
            non_retryable=(klass != "transient"),
        ) from exc


@activity.defn(name=KG_DELETE_BY_SOURCE_ACTIVITY)
async def kg_delete_by_source_activity(request: KGAdminRequest) -> KGAdminResult:
    """Source-key-targeted deletion (used by GC + migration)."""
    if request.op != "delete_by_source" or not request.source_key:
        raise ApplicationError(
            "delete_by_source requires op='delete_by_source' and source_key",
            type="document",
            non_retryable=True,
        )
    svc = _require_service()
    try:
        stats = svc.delete_by_source(request.source_key)
    except ApplicationError:
        raise
    except Exception as exc:
        klass = _classify_error(exc)
        raise ApplicationError(
            f"kg_delete_by_source failed: {exc}",
            type=klass,
            non_retryable=(klass != "transient"),
        ) from exc
    return KGAdminResult(ok=True, stats={k: int(v) for k, v in stats.items()})


@activity.defn(name=KG_HEALTH_ACTIVITY)
async def kg_health_activity(request: KGAdminRequest) -> KGAdminResult:
    """Backend stats / health probe."""
    if request.op != "health":
        raise ApplicationError(
            "kg_health requires op='health'",
            type="document",
            non_retryable=True,
        )
    svc = _require_service()
    try:
        stats = svc.health()
    except Exception as exc:
        klass = _classify_error(exc)
        raise ApplicationError(
            f"kg_health failed: {exc}",
            type=klass,
            non_retryable=(klass != "transient"),
        ) from exc
    return KGAdminResult(ok=True, stats=stats)
