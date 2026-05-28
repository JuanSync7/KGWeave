"""v1.14-#1: direct unit tests for ``_is_namespace_participant``.

Pins the predicate's boundary contract:
- Classic package (``__init__.py`` present) → False.
- Directory with a ``.py`` file and no ``__init__.py`` → True.
- Recursive: subdir whose ``.py`` participates → True.
- Empty subtree (no ``.py`` anywhere) → False.
- Fixtures-bucket stop (``<repo>/tests/.../fixtures/py``) → False.
- Depth-cap: ``.py`` only beyond ``_NS_WALK_MAX_DEPTH`` → False.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph.builders.py.writer import (
    _NS_WALK_MAX_DEPTH,
    _is_namespace_participant,
    _is_namespace_participant_cached,
)


@pytest.fixture(autouse=True)
def _clear_predicate_cache():
    """Each test sees a clean memoisation table — tmp_path paths can
    collide across tests within a single session if any system reuses
    inodes, and the predicate keys on the resolved absolute string."""
    _is_namespace_participant_cached.cache_clear()
    yield
    _is_namespace_participant_cached.cache_clear()


def test_classic_package_with_init_returns_false(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg_classic"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("x = 1\n")
    assert _is_namespace_participant(pkg) is False


def test_direct_py_no_init_returns_true(tmp_path: Path) -> None:
    ns = tmp_path / "ns_leaf"
    ns.mkdir()
    (ns / "mod.py").write_text("x = 1\n")
    assert _is_namespace_participant(ns) is True


def test_recursive_subdir_with_py_returns_true(tmp_path: Path) -> None:
    top = tmp_path / "ns_top"
    sub = top / "inner"
    sub.mkdir(parents=True)
    (sub / "leaf.py").write_text("y = 2\n")
    # No __init__.py anywhere, top has no direct .py, but the inner
    # subdir participates → top should participate.
    assert _is_namespace_participant(top) is True


def test_empty_subtree_returns_false(tmp_path: Path) -> None:
    top = tmp_path / "ns_empty"
    (top / "a" / "b" / "c").mkdir(parents=True)
    # No .py anywhere, no __init__.py.
    assert _is_namespace_participant(top) is False


def test_fixtures_bucket_stop_returns_false() -> None:
    fixtures_py = (
        Path(__file__).parent / ".." / ".." / "fixtures" / "py"
    ).resolve()
    # Existence sanity — the bucket lives in this repo.
    assert fixtures_py.is_dir(), (
        f"fixtures/py bucket missing at {fixtures_py}"
    )
    assert _is_namespace_participant(fixtures_py) is False


def test_depth_cap_does_not_false_positive(tmp_path: Path) -> None:
    # Build a chain that exceeds the predicate's recursion cap, with a
    # single .py file ONLY at the very bottom. The top should not
    # report True if the depth cap is enforced.
    chain_len = _NS_WALK_MAX_DEPTH + 3
    cur = tmp_path / "deep_root"
    cur.mkdir()
    top = cur
    for i in range(chain_len):
        cur = cur / f"d{i}"
        cur.mkdir()
    (cur / "buried.py").write_text("z = 3\n")
    assert _is_namespace_participant(top) is False
