"""Shared fixtures for the HTTP API tests."""

from __future__ import annotations

from typing import Optional

import pytest
from fastapi.testclient import TestClient

from kgweave.api.app import create_app
from kgweave.api.deps import set_service
from kgweave.contracts.http import (
    EntityResponse,
    ExpandResponse,
    HealthResponse,
    KGQueryMatchResponse,
    PathHopModel,
    PathResponse,
    PathResultModel,
    TermMatchResponse,
)
from kgweave.service.query_service import EntityNotFound, KGQueryService


class FakeKGQueryService(KGQueryService):
    """In-memory fake for transport-level tests."""

    def __init__(self) -> None:
        self.health_payload = HealthResponse(
            ok=True,
            contract_version="v1",
            backend="FakeBackend",
            stats={"nodes": 3, "edges": 2},
        )
        self.expand_payload = ExpandResponse(
            terms=["alpha", "beta"], graph_context="fake-context"
        )
        self.term_payload = TermMatchResponse(matches={"alpha": ["alpha-mod"]})
        self.kg_query_payload = KGQueryMatchResponse(
            matched=["alpha-mod", "beta-mod"], used_fallback=False,
        )
        self.entities: dict[str, EntityResponse] = {
            "alpha": EntityResponse(
                name="alpha", type="Module", mention_count=4,
                sources=["doc1.md"], aliases=["a"], summary="alpha module",
            ),
        }
        self.path_payload = PathResponse(
            results=[
                PathResultModel(
                    pattern_label="instantiates",
                    seed_entity="alpha",
                    terminal_entity="beta",
                    hops=[PathHopModel(
                        from_entity="alpha", edge_type="instantiates",
                        to_entity="beta",
                    )],
                )
            ]
        )
        self.expand_calls: list[tuple[str, Optional[int]]] = []
        self.term_calls: list[list[str]] = []
        self.kg_query_calls: list[tuple[str, int, int]] = []
        self.path_calls: list[tuple[str, list[list[str]]]] = []

    def health(self) -> HealthResponse:
        return self.health_payload

    def expand(self, query: str, depth: Optional[int] = None) -> ExpandResponse:
        self.expand_calls.append((query, depth))
        return self.expand_payload

    def match_terms(self, words: list[str]) -> TermMatchResponse:
        self.term_calls.append(list(words))
        return self.term_payload

    def match_kg_query(
        self, query: str, max_terms: int = 20, min_word_length: int = 3,
    ) -> KGQueryMatchResponse:
        self.kg_query_calls.append((query, max_terms, min_word_length))
        return self.kg_query_payload

    def get_entity(self, key: str) -> EntityResponse:
        try:
            return self.entities[key]
        except KeyError as exc:
            raise EntityNotFound(key) from exc

    def find_paths(
        self, seed_entity: str, patterns: list[list[str]]
    ) -> PathResponse:
        self.path_calls.append((seed_entity, patterns))
        return self.path_payload


@pytest.fixture
def fake_service() -> FakeKGQueryService:
    return FakeKGQueryService()


@pytest.fixture
def client(fake_service: FakeKGQueryService) -> TestClient:
    app = create_app(service=fake_service)
    set_service(fake_service)
    return TestClient(app)
