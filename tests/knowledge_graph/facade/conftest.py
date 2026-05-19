"""Shared facade-test fixtures: a tmp store seeded with the SV fifo corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_graph as kg

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sv"
FIFO_PATHS = [FIXTURE_DIR / "fifo.sv", FIXTURE_DIR / "fifo_pkg.sv"]


@pytest.fixture()
def facade_store(tmp_path: Path):
    """Open a tmp store and run the SV fifo extract through the facade."""
    store = kg.open_store(tmp_path / "kg.kuzu")
    try:
        kg.extract(store, source="sv", corpus="fifo", paths=FIFO_PATHS)
        yield store
    finally:
        store.close()


@pytest.fixture()
def empty_store(tmp_path: Path):
    """A facade-opened store with the schema initialised but no extracts."""
    store = kg.open_store(tmp_path / "kg.kuzu")
    try:
        yield store
    finally:
        store.close()
