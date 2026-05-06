# @summary
# Unit tests for KGWeave Temporal activity defs. Calls the activity
# functions directly (no Temporal worker / test server required) using a
# fake KGService. Verifies happy-path results plus structured failure
# classification (transient / document / system) on ApplicationError.
# Exports: (test module)
# @end-summary
"""Step 9: KGWeave activity-level unit tests."""

from __future__ import annotations

import pytest
from temporalio.exceptions import ApplicationError

from kgweave.contracts import (
    KGAdminRequest,
    KGAdminResult,
    KGIngestRequest,
    KGIngestResult,
)
from kgweave.service import KGService
from kgweave.worker import (
    kg_delete_by_source_activity,
    kg_health_activity,
    kg_phase2b_activity,
    set_service,
)


class _FakeService(KGService):
    def __init__(self) -> None:
        self.ingested: list[KGIngestRequest] = []
        self.deleted: list[str] = []
        self.fail_with: BaseException | None = None

    def extract_and_commit(self, request: KGIngestRequest) -> KGIngestResult:
        if self.fail_with is not None:
            raise self.fail_with
        self.ingested.append(request)
        return KGIngestResult(
            source_key=request.source_key,
            entities_added=2,
            triples_added=1,
            chunks_processed=1,
            elapsed_ms=1.0,
        )

    def delete_by_source(self, source_key: str) -> dict[str, int]:
        if self.fail_with is not None:
            raise self.fail_with
        self.deleted.append(source_key)
        return {"entities_removed": 1, "triples_removed": 0}

    def health(self) -> dict[str, object]:
        if self.fail_with is not None:
            raise self.fail_with
        return {"nodes": 0, "edges": 0, "backend": "fake"}


@pytest.fixture
def fake() -> _FakeService:
    svc = _FakeService()
    set_service(svc)
    return svc


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_phase2b_returns_result(fake: _FakeService) -> None:
    res = await kg_phase2b_activity(
        KGIngestRequest(source_key="doc1.md", clean_text="hello")
    )
    assert isinstance(res, KGIngestResult)
    assert res.source_key == "doc1.md"
    assert res.entities_added == 2
    assert fake.ingested[0].clean_text == "hello"


async def test_delete_returns_result(fake: _FakeService) -> None:
    res = await kg_delete_by_source_activity(
        KGAdminRequest(op="delete_by_source", source_key="doc1.md")
    )
    assert isinstance(res, KGAdminResult)
    assert res.ok is True
    assert res.stats == {"entities_removed": 1, "triples_removed": 0}
    assert fake.deleted == ["doc1.md"]


async def test_health_returns_result(fake: _FakeService) -> None:
    res = await kg_health_activity(KGAdminRequest(op="health"))
    assert res.ok is True
    assert res.stats["backend"] == "fake"


# ---------------------------------------------------------------------------
# Service-not-bound guard
# ---------------------------------------------------------------------------


async def test_no_service_bound_raises_system_error() -> None:
    set_service(None)  # type: ignore[arg-type]
    with pytest.raises(ApplicationError) as excinfo:
        await kg_phase2b_activity(
            KGIngestRequest(source_key="doc1.md", clean_text="x")
        )
    assert excinfo.value.type == "system"
    assert excinfo.value.non_retryable is True


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------


async def test_phase2b_transient_is_retryable(fake: _FakeService) -> None:
    fake.fail_with = RuntimeError("rate-limit")
    with pytest.raises(ApplicationError) as excinfo:
        await kg_phase2b_activity(
            KGIngestRequest(source_key="doc1.md", clean_text="x")
        )
    assert excinfo.value.type == "transient"
    assert excinfo.value.non_retryable is False


async def test_phase2b_document_is_permanent(fake: _FakeService) -> None:
    fake.fail_with = ValueError("bad SV syntax")
    with pytest.raises(ApplicationError) as excinfo:
        await kg_phase2b_activity(
            KGIngestRequest(source_key="doc1.md", clean_text="x")
        )
    assert excinfo.value.type == "document"
    assert excinfo.value.non_retryable is True


async def test_phase2b_system_is_permanent(fake: _FakeService) -> None:
    fake.fail_with = ImportError("missing model file")
    with pytest.raises(ApplicationError) as excinfo:
        await kg_phase2b_activity(
            KGIngestRequest(source_key="doc1.md", clean_text="x")
        )
    assert excinfo.value.type == "system"
    assert excinfo.value.non_retryable is True


# ---------------------------------------------------------------------------
# Schema guards on the activity boundary
# ---------------------------------------------------------------------------


async def test_delete_with_wrong_op_rejected(fake: _FakeService) -> None:
    # Pydantic blocks construction of an invalid op, but if a payload
    # somehow arrives mismatched, the activity should refuse cleanly.
    bad = KGAdminRequest(op="health")  # op != delete_by_source
    with pytest.raises(ApplicationError) as excinfo:
        await kg_delete_by_source_activity(bad)
    assert excinfo.value.type == "document"
    assert excinfo.value.non_retryable is True


async def test_health_with_wrong_op_rejected(fake: _FakeService) -> None:
    bad = KGAdminRequest(op="delete_by_source", source_key="x")
    with pytest.raises(ApplicationError) as excinfo:
        await kg_health_activity(bad)
    assert excinfo.value.type == "document"
    assert excinfo.value.non_retryable is True
