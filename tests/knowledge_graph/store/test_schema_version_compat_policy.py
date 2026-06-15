"""Configurable compat policy on ``verify_or_migrate_schema_version`` (v1.5-#4).

Adds a ``compat`` kwarg accepting:

* ``"semver-major"`` (default; current behaviour) — same major OK,
  newer expected minor/patch OK, downgrades/major-bumps rejected.
* ``"exact"`` — stored version must equal expected exactly. Any patch
  difference is rejected.
* ``"any"`` — any (parseable) stored version is accepted.

Default unchanged: callers passing nothing still get semver-major.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph.store import KGStore
from knowledge_graph.store import schema as _schema_mod
from knowledge_graph.store.schema import (
    SchemaVersionMismatch,
    verify_or_migrate_schema_version,
)


def _set_stored_version(conn, version: str) -> None:
    """Force the ``:Meta.schema_version`` row for a freshly-opened store."""
    conn.execute(
        "MERGE (m:Meta {singleton_key: $k}) SET m.schema_version = $v",
        {"k": "kgweave", "v": version},
    )


# ---------------------------------------------------------------- semver-major
def test_compat_semver_major_same_major_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default ``semver-major``: stored 1.3.0 + expected 1.4.0 -> OK."""
    db = tmp_path / "kg.kuzu"
    s = KGStore.open(db)
    try:
        _set_stored_version(s.conn, "1.3.0")
        monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.4.0")
        # Default kwarg path:
        assert (
            verify_or_migrate_schema_version(s.conn, compat="semver-major")
            == "1.3.0"
        )
    finally:
        s.close()


def test_compat_semver_major_different_major_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``semver-major``: different major rejected."""
    db = tmp_path / "kg.kuzu"
    s = KGStore.open(db)
    try:
        _set_stored_version(s.conn, "1.3.0")
        monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "2.0.0")
        with pytest.raises(SchemaVersionMismatch) as ei:
            verify_or_migrate_schema_version(s.conn, compat="semver-major")
        assert ei.value.compat_policy == "semver-major"
    finally:
        s.close()


# ---------------------------------------------------------------- exact
def test_compat_exact_patch_difference_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``exact``: any patch difference rejected (even forward-compat under semver-major)."""
    db = tmp_path / "kg.kuzu"
    s = KGStore.open(db)
    try:
        _set_stored_version(s.conn, "1.3.0")
        monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.3.1")
        # Under semver-major this would be accepted; under exact it must raise.
        with pytest.raises(SchemaVersionMismatch) as ei:
            verify_or_migrate_schema_version(s.conn, compat="exact")
        assert ei.value.compat_policy == "exact"
        assert ei.value.stored == "1.3.0"
        assert ei.value.expected == "1.3.1"
    finally:
        s.close()


def test_compat_exact_equal_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``exact``: identical stored/expected accepted."""
    db = tmp_path / "kg.kuzu"
    s = KGStore.open(db)
    try:
        _set_stored_version(s.conn, "1.3.0")
        monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.3.0")
        assert (
            verify_or_migrate_schema_version(s.conn, compat="exact") == "1.3.0"
        )
    finally:
        s.close()


# ---------------------------------------------------------------- any
def test_compat_any_accepts_major_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``any``: even a different-major store opens."""
    db = tmp_path / "kg.kuzu"
    s = KGStore.open(db)
    try:
        _set_stored_version(s.conn, "9.9.9")
        monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.3.0")
        # Would raise under semver-major; under any it returns the stored val.
        assert (
            verify_or_migrate_schema_version(s.conn, compat="any") == "9.9.9"
        )
    finally:
        s.close()


# ---------------------------------------------------------------- default unchanged
def test_default_compat_is_semver_major(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting the kwarg keeps semver-major behaviour."""
    db = tmp_path / "kg.kuzu"
    s = KGStore.open(db)
    try:
        _set_stored_version(s.conn, "1.3.0")
        monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "2.0.0")
        with pytest.raises(SchemaVersionMismatch) as ei:
            verify_or_migrate_schema_version(s.conn)
        assert ei.value.compat_policy == "semver-major"
    finally:
        s.close()
