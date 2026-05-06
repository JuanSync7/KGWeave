# @summary
# Wire contract between RagWeave (caller) and KGWeave (Temporal worker).
# Both repos pin the same CONTRACT_VERSION. RagWeave never imports KGWeave
# code — it dispatches activities by name on KG_TASK_QUEUE using the
# Pydantic schemas defined here.
# Exports: CONTRACT_VERSION, KG_TASK_QUEUE, KG_PHASE2B_ACTIVITY,
#          KG_DELETE_BY_SOURCE_ACTIVITY, KG_HEALTH_ACTIVITY,
#          KGIngestRequest, KGIngestResult, KGAdminRequest, KGAdminResult,
#          KGErrorClass
# Deps: kgweave.contracts.constants, kgweave.contracts.schemas
# @end-summary
"""KGWeave wire contract — task queue, activity names, Pydantic schemas."""

from kgweave.contracts.constants import (
    CONTRACT_VERSION,
    KG_DELETE_BY_SOURCE_ACTIVITY,
    KG_HEALTH_ACTIVITY,
    KG_PHASE2B_ACTIVITY,
    KG_TASK_QUEUE,
)
from kgweave.contracts.schemas import (
    KGAdminRequest,
    KGAdminResult,
    KGErrorClass,
    KGIngestRequest,
    KGIngestResult,
)

__all__ = [
    "CONTRACT_VERSION",
    "KG_TASK_QUEUE",
    "KG_PHASE2B_ACTIVITY",
    "KG_DELETE_BY_SOURCE_ACTIVITY",
    "KG_HEALTH_ACTIVITY",
    "KGIngestRequest",
    "KGIngestResult",
    "KGAdminRequest",
    "KGAdminResult",
    "KGErrorClass",
]
