"""Shared fixtures for the SV builder test suite.

Exposes the SV fixture corpus from ``tests/knowledge_graph/fixtures/sv/`` as
the ``sv_fixtures`` fixture and provides a per-file parametrisation helper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "sv"
)


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.sv"))


@pytest.fixture(scope="session")
def sv_fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def sv_fixtures() -> list[Path]:
    return _fixture_paths()


# --- writer-suite shared fixtures (session-scoped to avoid 90s rebuilds) -----


@pytest.fixture(scope="session")
def sv_corpus_paths() -> list[Path]:
    return _fixture_paths()


@pytest.fixture(scope="session")
def sv_corpus_graph(sv_corpus_paths: list[Path]) -> dict[str, Any]:
    from knowledge_graph.builders.sv import build_kg

    graph, _trees, _comp = build_kg(sv_corpus_paths)
    return graph


@pytest.fixture(scope="session")
def sv_corpus_store(
    tmp_path_factory: pytest.TempPathFactory,
    sv_corpus_paths: list[Path],
) -> tuple[Any, dict[str, Any], dict[str, Any], Any]:
    """``(store, graph, origins_by_prefix, stats)`` — built once per session.

    Treat the returned store as read-only; idempotency tests build their
    own per-test stores.
    """
    from knowledge_graph.builders.sv import build_and_store
    from knowledge_graph.store import KGStore

    db_dir = tmp_path_factory.mktemp("kg_writer_session")
    store = KGStore.open(db_dir / "kg.kuzu")
    graph, origins, stats = build_and_store(
        store, sv_corpus_paths, corpus="fixtures"
    )
    return store, graph, origins, stats


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "sv_fixture" in metafunc.fixturenames:
        paths = _fixture_paths()
        metafunc.parametrize(
            "sv_fixture",
            paths,
            ids=[p.name for p in paths],
        )
