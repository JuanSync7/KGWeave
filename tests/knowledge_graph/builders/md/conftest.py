"""Shared fixtures for the MD builder test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SV_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "sv"
)


@pytest.fixture(scope="session")
def md_fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def md_fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.md"))


@pytest.fixture(scope="session")
def sv_fixture_paths_for_md() -> list[Path]:
    return [SV_FIXTURE_DIR / "fifo.sv", SV_FIXTURE_DIR / "fifo_pkg.sv"]
