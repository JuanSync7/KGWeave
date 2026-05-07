# @summary
# GET /v1/entities/{key} — single entity probe. Returns 404 via the
# EntityNotFound exception handler when the key is missing.
# @end-summary
"""Entity probe endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from kgweave.api.deps import AuthDep, ServiceDep
from kgweave.contracts.http import EntityResponse
from kgweave.service.query_service import KGQueryService

router = APIRouter(tags=["query"], dependencies=[AuthDep])


@router.get("/entities/{key}", response_model=EntityResponse)
def get_entity(
    key: str,
    service: KGQueryService = ServiceDep,
) -> EntityResponse:
    return service.get_entity(key)
