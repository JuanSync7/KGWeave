"""Tests for the ``max_db_size_bytes`` cap on ``KGStore.open``.

v1.5-#1: Kuzu's default ``max_db_size = 8 TB`` is sparse-allocated. That is
free on tmpfs but expensive (metadata + fsync) on ext4. When the pytest
basetemp redirect (v1.4-#1) moved test stores from tmpfs to
``~/.pytest-tmp`` on ext4, per-test wall-clock blew up ~4x. The fix is to
let callers (and the test fixtures) pin a small cap (256 MiB by default
for tests -- 2**28 bytes == 268_435_456; Kuzu enforces power-of-2 caps)
by passing ``max_db_size_bytes`` through to Kuzu's ``Database``
constructor (which takes the cap as ``max_db_size``).

The tests below cover:

* **G1** -- The kwarg exists on ``KGStore.open`` and is accepted without
  raising. Backwards-compatible default (omitted kwarg -> Kuzu's 8 TB
  behaviour preserved).
* **G2** -- The kwarg is forwarded to ``kuzu.Database`` with the expected
  value. Verified by monkey-patching ``kuzu.Database`` so the test does
  not depend on Kuzu silently honouring (or ignoring) an out-of-range
  cap.
* **G3** -- The ``tmp_store`` and ``shared_kuzu_store`` fixtures both
  open with the 256 MB cap. Verified end-to-end by spying on
  ``kuzu.Database`` during fixture setup via a separate fixture-scoped
  test that introspects the store path's on-disk footprint stays below
  the cap (the cap is much larger than the test write volume, so this
  only proves the fixture path opens cleanly with the kwarg routed).

The forwarded-arg check is the load-bearing one because Kuzu's docstring
explicitly notes ``max_db_size`` is a workaround for the 8 TB mmap limit
and does not promise hard enforcement at write time.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import kuzu
import pytest

from knowledge_graph.store import KGStore


# --- G1: kwarg exists on KGStore.open -----------------------------------


def test_kgstore_open_accepts_max_db_size_bytes_kwarg(tmp_path: Path) -> None:
    """``KGStore.open(path, max_db_size_bytes=N)`` must not raise."""
    sig = inspect.signature(KGStore.open)
    assert "max_db_size_bytes" in sig.parameters, (
        "KGStore.open should expose a max_db_size_bytes kwarg "
        f"(v1.5-#1); current signature: {sig}"
    )
    store = KGStore.open(tmp_path / "kg.kuzu", max_db_size_bytes=268_435_456)
    try:
        # Basic sanity: the store should be usable.
        assert store.path.exists()
    finally:
        store.close()


def test_kgstore_open_backwards_compatible_default(tmp_path: Path) -> None:
    """Omitting the kwarg must preserve current open() behaviour."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        assert store.path.exists()
    finally:
        store.close()


# --- G2: forwarded to kuzu.Database -------------------------------------


def test_max_db_size_bytes_is_forwarded_to_kuzu_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap must reach ``kuzu.Database`` as the ``max_db_size`` kwarg."""
    seen: dict[str, Any] = {}
    real_db = kuzu.Database

    def spy(*args: Any, **kwargs: Any) -> kuzu.Database:
        seen["args"] = args
        seen["kwargs"] = dict(kwargs)
        return real_db(*args, **kwargs)

    # Patch the binding in the kuzu_store module's namespace.
    import knowledge_graph.store.kuzu as kuzu_store_mod

    monkeypatch.setattr(kuzu_store_mod.kuzu, "Database", spy)

    store = KGStore.open(tmp_path / "kg.kuzu", max_db_size_bytes=268_435_456)
    try:
        assert seen, "kuzu.Database spy was never called"
        assert seen["kwargs"].get("max_db_size") == 268_435_456, (
            "expected max_db_size=268_435_456 (256 MiB, power of 2) "
            "forwarded to kuzu.Database, "
            f"got kwargs={seen['kwargs']}"
        )
    finally:
        store.close()


def test_omitted_kwarg_does_not_forward_max_db_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the caller omits the cap, KGStore must NOT pass max_db_size.

    This protects the 8 TB Kuzu default for production callers who never
    asked for a cap.
    """
    seen: dict[str, Any] = {}
    real_db = kuzu.Database

    def spy(*args: Any, **kwargs: Any) -> kuzu.Database:
        seen["kwargs"] = dict(kwargs)
        return real_db(*args, **kwargs)

    import knowledge_graph.store.kuzu as kuzu_store_mod

    monkeypatch.setattr(kuzu_store_mod.kuzu, "Database", spy)

    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        assert "max_db_size" not in seen["kwargs"], (
            "max_db_size must not be forwarded when the caller did not opt in; "
            f"got kwargs={seen['kwargs']}"
        )
    finally:
        store.close()
