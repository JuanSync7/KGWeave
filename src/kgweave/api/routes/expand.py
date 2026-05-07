# @summary
# POST /v1/expand — graph query expansion endpoint.
# @end-summary
"""Query expansion endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from kgweave.api.deps import AuthDep, ServiceDep
from kgweave.contracts.http import ExpandRequest, ExpandResponse
from kgweave.service.query_service import KGQueryService

router = APIRouter(tags=["query"], dependencies=[AuthDep])


@router.post("/expand", response_model=ExpandResponse)
def expand(
    payload: ExpandRequest,
    service: KGQueryService = ServiceDep,
) -> ExpandResponse:
    return service.expand(payload.query, depth=payload.depth)
