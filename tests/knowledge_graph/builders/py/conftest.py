"""Per-directory pytest infra for the Python builder suite.

Like the SV connector dir, full extract round-trips touch Kuzu and can
breach the global 60 s budget; bump to 300 s for everything collected
here.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
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
