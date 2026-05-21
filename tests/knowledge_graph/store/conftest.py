"""Shared pytest fixtures for store tests.

Kuzu-backed integration tests routinely run 60-120 s on this box because each
test spins a fresh embedded DB, runs a real SV extraction, and re-opens. The
global ``timeout = 60`` guard would trip on these tests by design -- so this
conftest bumps the per-test timeout to 300 s for everything under
``tests/knowledge_graph/store/``. The lower 60 s default still protects the
rest of the suite from sibling-pytest I/O wedges.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph.store import KGStore


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Apply a 300 s timeout to every test collected from this directory."""
    here = Path(__file__).resolve().parent
    marker = pytest.mark.timeout(300)
    for item in items:
        try:
            item_path = Path(item.fspath).resolve()
        except (TypeError, ValueError):
            continue
        try:
            item_path.relative_to(here)
        except ValueError:
            continue
        item.add_marker(marker)


@pytest.fixture()
def tmp_store(tmp_path: Path) -> KGStore:
    """Open a fresh KGStore backed by a tmp_path Kuzu directory."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        yield store
    finally:
        store.close()
