"""Round-trip tests for HTTPKGQueryService against the FastAPI app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kgweave.api.app import create_app
from kgweave.api.deps import set_service
from kgweave.client.factory import get_client, reset_client
from kgweave.client.http_client import HTTPKGQueryService
from kgweave.service.query_service import EntityNotFound

from tests.api.conftest import FakeKGQueryService


def _http_client_against_app(service) -> HTTPKGQueryService:
    set_service(service)
    app = create_app(service=service)
    inner = TestClient(app)
    return HTTPKGQueryService(base_url="http://testserver", client=inner)


def test_http_client_health() -> None:
    fake = FakeKGQueryService()
    client = _http_client_against_app(fake)
    try:
        result = client.health()
        assert result.ok is True
        assert result.backend == "FakeBackend"
    finally:
        client.close()


def test_http_client_expand_and_paths() -> None:
    fake = FakeKGQueryService()
    client = _http_client_against_app(fake)
    try:
        exp = client.expand("rtl", depth=2)
        assert exp.terms == ["alpha", "beta"]
        assert fake.expand_calls == [("rtl", 2)]

        paths = client.find_paths("alpha", [["instantiates"]])
        assert paths.results[0].terminal_entity == "beta"
    finally:
        client.close()


def test_http_client_entity_404_raises() -> None:
    fake = FakeKGQueryService()
    client = _http_client_against_app(fake)
    try:
        with pytest.raises(EntityNotFound):
            client.get_entity("missing")
    finally:
        client.close()


def test_factory_returns_in_process_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KGWEAVE_API_URL", raising=False)
    reset_client()
    client = get_client()
    # Default in-process service is not the HTTP variant
    assert not isinstance(client, HTTPKGQueryService)


def test_factory_returns_http_client_when_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KGWEAVE_API_URL", "http://kg.example/")
    reset_client()
    client = get_client()
    assert isinstance(client, HTTPKGQueryService)
    reset_client()
