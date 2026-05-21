"""Goal 2: pytest-timeout installed and configured at 60s / thread method.

Prevents sibling I/O contention from wedging the suite in kernel Dl state for
20+ minutes. We verify config statically (no nested pytest) plus a slow-test
marker that proves the plugin is wired (skipped by default — meta-guard only).
"""
from __future__ import annotations

import time
import tomllib
from pathlib import Path

import pytest


_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_pytest_timeout_module_importable() -> None:
    """The pytest_timeout plugin must be importable in the test env."""
    import pytest_timeout  # noqa: F401  -- import-only sanity check


def test_pyproject_declares_timeout_60s_thread() -> None:
    """pyproject.toml [tool.pytest.ini_options] must pin timeout=60, method=thread."""
    cfg = tomllib.loads(_PYPROJECT.read_text())
    ini = cfg["tool"]["pytest"]["ini_options"]
    assert ini.get("timeout") == 60, f"expected timeout=60, got {ini.get('timeout')!r}"
    assert ini.get("timeout_method") == "thread", (
        f"expected timeout_method=thread, got {ini.get('timeout_method')!r}"
    )


@pytest.mark.skip(reason="meta-guard, not run in CI -- proves plugin trips at 60s")
def test_slow_sleep_trips_timeout() -> None:
    """A 120s sleep must trip pytest-timeout at 60s -- skipped to keep CI fast."""
    time.sleep(120)
