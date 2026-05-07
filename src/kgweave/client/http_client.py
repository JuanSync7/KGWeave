# @summary
# HTTP-backed KGQueryService implementation. Delegates each method to the
# matching v1 endpoint via httpx, validates the response with the shared
# Pydantic models, and translates 404 → EntityNotFound.
# Exports: HTTPKGQueryService
# Deps: httpx, kgweave.contracts.http
# @end-summary
"""HTTP transport for the read-side KG service."""

from __future__ import annotations

from typing import Optional

import httpx

from kgweave.contracts.http import (
    EntityResponse,
    ExpandRequest,
    ExpandResponse,
    HealthResponse,
    KGQueryMatchRequest,
    KGQueryMatchResponse,
    PathRequest,
    PathResponse,
    TermMatchRequest,
    TermMatchResponse,
)
from kgweave.service.query_service import EntityNotFound, KGQueryService


class HTTPKGQueryService(KGQueryService):
    """Calls a remote KGWeave API. Same interface as the in-process service.

    The HTTP client is created lazily and reused for connection pooling.
    Callers may pass their own ``client`` (e.g. an httpx.MockTransport in
    tests) — the facade will not close clients it didn't construct.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: Optional[str] = None,
        timeout: float = 5.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._owned = client is None
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client or httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owned:
            self._client.close()

    # ------------------------------------------------------------------
    # KGQueryService implementation
    # ------------------------------------------------------------------

    def health(self) -> HealthResponse:
        resp = self._client.get("/v1/health")
        resp.raise_for_status()
        return HealthResponse.model_validate(resp.json())

    def expand(self, query: str, depth: Optional[int] = None) -> ExpandResponse:
        body = ExpandRequest(query=query, depth=depth).model_dump(
            exclude_none=True
        )
        resp = self._client.post("/v1/expand", json=body)
        resp.raise_for_status()
        return ExpandResponse.model_validate(resp.json())

    def match_terms(self, words: list[str]) -> TermMatchResponse:
        body = TermMatchRequest(words=words).model_dump()
        resp = self._client.post("/v1/term-index/match", json=body)
        resp.raise_for_status()
        return TermMatchResponse.model_validate(resp.json())

    def match_kg_query(
        self,
        query: str,
        max_terms: int = 20,
        min_word_length: int = 3,
    ) -> KGQueryMatchResponse:
        body = KGQueryMatchRequest(
            query=query, max_terms=max_terms, min_word_length=min_word_length,
        ).model_dump()
        resp = self._client.post("/v1/term-index/query", json=body)
        resp.raise_for_status()
        return KGQueryMatchResponse.model_validate(resp.json())

    def get_entity(self, key: str) -> EntityResponse:
        resp = self._client.get(f"/v1/entities/{key}")
        if resp.status_code == 404:
            raise EntityNotFound(key)
        resp.raise_for_status()
        return EntityResponse.model_validate(resp.json())

    def find_paths(
        self, seed_entity: str, patterns: list[list[str]]
    ) -> PathResponse:
        body = PathRequest(seed_entity=seed_entity, patterns=patterns).model_dump()
        resp = self._client.post("/v1/paths", json=body)
        resp.raise_for_status()
        return PathResponse.model_validate(resp.json())
