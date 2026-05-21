"""Per-directory test infra for the connector suite.

Connector tests exercise full SV->KG extraction against an embedded Kuzu DB.
Like ``tests/knowledge_graph/store/``, individual tests can run 60-120 s.
The global ``timeout = 60`` guard would deterministically trip on these, so we
bump the per-test budget to 300 s for everything collected under this dir.
The lower 60 s default still protects the rest of the suite from sibling I/O
wedges.
"""

from __future__ import annotations

from pathlib import Path

import pytest


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
