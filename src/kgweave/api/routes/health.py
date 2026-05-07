# @summary
# GET /v1/health — returns liveness, contract version, and backend stats.
# No auth required; deliberately the only unauthenticated route.
# @end-summary
"""Liveness probe."""

from __future__ import annotations

from fastapi import APIRouter

from kgweave.api.deps import ServiceDep
from kgweave.contracts.http import HealthResponse
from kgweave.service.query_service import KGQueryService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(service: KGQueryService = ServiceDep) -> HealthResponse:
    return service.health()
