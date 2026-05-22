"""Shared facade-test fixtures: a tmp store seeded with the SV fifo corpus.

Per-test timeout bump
=====================
The global timeout pinned in ``pyproject.toml`` is 60 s (v1.4-#1). The
facade tests in this directory all share a fixture that runs the full
SV ``fifo`` extract through the public ``kg.extract`` facade -- which
takes ~125 s on the dev box's ext4 basetemp (extract dominates; see
JOURNAL v1.5-#1 for the profile). Without an override the fixture
times out before the first test runs. We follow the same pattern used
by ``tests/knowledge_graph/store/conftest.py`` and bump every collected
item under this directory to a 300 s timeout. The store-tests bump
covers a similar Kuzu-heavy I/O path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_graph as kg

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sv"
FIFO_PATHS = [FIXTURE_DIR / "fifo.sv", FIXTURE_DIR / "fifo_pkg.sv"]


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Apply a 450 s timeout to every test collected from this directory.

    Mirrors the store/conftest override -- see this module's docstring
    for the reason (extract takes ~125 s on ext4 basetemp). Pinned at
    450 s (not 300 s like store/) because ``test_quickstart_runs.py``
    runs the quickstart in a subprocess with a 400 s subprocess timeout
    of its own (v1.5-#1 G5); the pytest-timeout marker must sit above
    that to let the subprocess timeout fire first with a useful
    diagnostic. Tests that declare their own ``@pytest.mark.timeout``
    (e.g. ``test_quickstart_perf`` at 260 s) override this default.
    """
    here = Path(__file__).resolve().parent
    marker = pytest.mark.timeout(450)
    for item in items:
        try:
            item_path = Path(item.fspath).resolve()
        except (TypeError, ValueError):
            continue
        try:
            item_path.relative_to(here)
        except ValueError:
            continue
        # Don't clobber tests that already carry their own timeout marker
        # (test_quickstart_perf uses a tighter budget).
        if item.get_closest_marker("timeout") is not None:
            continue
        item.add_marker(marker)


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
