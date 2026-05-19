"""Shared pytest fixtures for store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph.store import KGStore


@pytest.fixture()
def tmp_store(tmp_path: Path) -> KGStore:
    """Open a fresh KGStore backed by a tmp_path Kuzu directory."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        yield store
    finally:
        store.close()
