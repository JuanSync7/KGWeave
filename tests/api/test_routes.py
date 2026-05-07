"""Endpoint-level tests using FastAPI TestClient + a fake service."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from kgweave.api.app import create_app
from kgweave.api.deps import set_service

from tests.api.conftest import FakeKGQueryService


def test_health_returns_backend_snapshot(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["contract_version"] == "v1"
    assert body["backend"] == "FakeBackend"
    assert body["stats"] == {"nodes": 3, "edges": 2}


def test_expand_forwards_query_and_depth(
    client: TestClient, fake_service: FakeKGQueryService
) -> None:
    resp = client.post("/v1/expand", json={"query": "rtl", "depth": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["terms"] == ["alpha", "beta"]
    assert body["graph_context"] == "fake-context"
    assert fake_service.expand_calls == [("rtl", 2)]


def test_expand_rejects_invalid_payload(client: TestClient) -> None:
    resp = client.post("/v1/expand", json={"query": ""})
    assert resp.status_code == 422


def test_term_index_match(
    client: TestClient, fake_service: FakeKGQueryService
) -> None:
    resp = client.post(
        "/v1/term-index/match", json={"words": ["alpha", "missing"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matches"] == {"alpha": ["alpha-mod"]}
    assert fake_service.term_calls == [["alpha", "missing"]]


def test_kg_query_endpoint(
    client: TestClient, fake_service: FakeKGQueryService
) -> None:
    resp = client.post(
        "/v1/term-index/query",
        json={"query": "alpha core module", "max_terms": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] == ["alpha-mod", "beta-mod"]
    assert body["used_fallback"] is False
    assert fake_service.kg_query_calls == [("alpha core module", 5, 3)]


def test_get_entity_found(client: TestClient) -> None:
    resp = client.get("/v1/entities/alpha")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "alpha"
    assert body["type"] == "Module"
    assert body["mention_count"] == 4


def test_get_entity_404(client: TestClient) -> None:
    resp = client.get("/v1/entities/nope")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "entity_not_found"
    assert "nope" in body["detail"]


def test_paths_endpoint(
    client: TestClient, fake_service: FakeKGQueryService
) -> None:
    resp = client.post(
        "/v1/paths",
        json={"seed_entity": "alpha", "patterns": [["instantiates"]]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["seed_entity"] == "alpha"
    assert result["terminal_entity"] == "beta"
    assert result["hops"][0]["edge_type"] == "instantiates"
    assert fake_service.path_calls == [("alpha", [["instantiates"]])]


def test_health_does_not_require_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGWEAVE_API_TOKEN", "secret")
    fake = FakeKGQueryService()
    set_service(fake)
    app = create_app(service=fake)
    with TestClient(app) as cli:
        assert cli.get("/v1/health").status_code == 200


def test_protected_route_requires_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KGWEAVE_API_TOKEN", "secret")
    fake = FakeKGQueryService()
    set_service(fake)
    app = create_app(service=fake)
    with TestClient(app) as cli:
        resp = cli.post("/v1/expand", json={"query": "x"})
        assert resp.status_code == 401

        resp = cli.post(
            "/v1/expand",
            json={"query": "x"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 403

        resp = cli.post(
            "/v1/expand",
            json={"query": "x"},
            headers={"Authorization": "Bearer secret"},
        )
        assert resp.status_code == 200


@pytest.fixture(autouse=True)
def _clear_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KGWEAVE_API_TOKEN", raising=False)
    # Avoid leaking auth env between tests
    yield
    if "KGWEAVE_API_TOKEN" in os.environ:
        del os.environ["KGWEAVE_API_TOKEN"]
