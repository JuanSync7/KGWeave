# @summary
# POST /v1/paths — multi-hop path-pattern evaluation. Uses POST (not GET)
# because the patterns argument is structured (list[list[str]]).
# @end-summary
"""Path-pattern evaluation endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from kgweave.api.deps import AuthDep, ServiceDep
from kgweave.contracts.http import PathRequest, PathResponse
from kgweave.service.query_service import KGQueryService

router = APIRouter(tags=["query"], dependencies=[AuthDep])


@router.post("/paths", response_model=PathResponse)
def find_paths(
    payload: PathRequest,
    service: KGQueryService = ServiceDep,
) -> PathResponse:
    return service.find_paths(payload.seed_entity, payload.patterns)
