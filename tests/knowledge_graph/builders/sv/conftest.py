"""Shared fixtures for the SV builder test suite.

Exposes the SV fixture corpus from ``tests/knowledge_graph/fixtures/sv/`` as
the ``sv_fixtures`` fixture and provides a per-file parametrisation helper.
"""

from __future__ import annotations

from pathlib import Path

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


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "sv_fixture" in metafunc.fixturenames:
        paths = _fixture_paths()
        metafunc.parametrize(
            "sv_fixture",
            paths,
            ids=[p.name for p in paths],
        )
