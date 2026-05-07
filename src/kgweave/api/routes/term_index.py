# @summary
# POST /v1/term-index/match — vocabulary lookup against the cached term index.
# @end-summary
"""Term-index match endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from kgweave.api.deps import AuthDep, ServiceDep
from kgweave.contracts.http import (
    KGQueryMatchRequest,
    KGQueryMatchResponse,
    TermMatchRequest,
    TermMatchResponse,
)
from kgweave.service.query_service import KGQueryService

router = APIRouter(tags=["query"], dependencies=[AuthDep])


@router.post("/term-index/match", response_model=TermMatchResponse)
def match_terms(
    payload: TermMatchRequest,
    service: KGQueryService = ServiceDep,
) -> TermMatchResponse:
    return service.match_terms(payload.words)


@router.post("/term-index/query", response_model=KGQueryMatchResponse)
def match_kg_query(
    payload: KGQueryMatchRequest,
    service: KGQueryService = ServiceDep,
) -> KGQueryMatchResponse:
    return service.match_kg_query(
        payload.query,
        max_terms=payload.max_terms,
        min_word_length=payload.min_word_length,
    )
