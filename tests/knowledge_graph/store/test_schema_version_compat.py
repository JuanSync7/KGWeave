"""Semver-aware ``:Meta`` compatibility policy tests (v1.3-#2).

Replaces the v1.2 literal-equality check with a major-pinned,
minor/patch forward-compatible policy:

* same major + ``(expected.minor, expected.patch) >= (stored.minor, stored.patch)``
  → open succeeds (a newer running build can read an older patch store)
* otherwise (different major, or downgrade attempt) → :class:`SchemaVersionMismatch`
"""

from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_graph as kg
from knowledge_graph.store import KGStore
from knowledge_graph.store import schema as _schema_mod


# ---------------------------------------------------------------- pure helper
def test_is_compatible_equal() -> None:
    """Same major/minor/patch always compatible."""
    assert _schema_mod._is_compatible("1.3.0", "1.3.0") is True


def test_is_compatible_patch_forward() -> None:
    """Newer patch on expected reads older patch store."""
    assert _schema_mod._is_compatible("1.3.0", "1.3.1") is True


def test_is_compatible_minor_forward() -> None:
    """Newer minor on expected reads older minor store."""
    assert _schema_mod._is_compatible("1.3.0", "1.4.0") is True


def test_is_compatible_patch_downgrade_rejected() -> None:
    """Older expected cannot open a newer-patch store."""
    assert _schema_mod._is_compatible("1.3.1", "1.3.0") is False


def test_is_compatible_minor_downgrade_rejected() -> None:
    """Older expected minor cannot open a newer-minor store."""
    assert _schema_mod._is_compatible("1.4.0", "1.3.9") is False


def test_is_compatible_major_bump_rejected() -> None:
    """Different major never compatible (either direction)."""
    assert _schema_mod._is_compatible("1.9.9", "2.0.0") is False
    assert _schema_mod._is_compatible("2.0.0", "1.9.9") is False


# ---------------------------------------------------------------- live store
def _meta_rows(store: KGStore) -> list[str]:
    res = store.conn.execute("MATCH (m:Meta) RETURN m.schema_version")
    out: list[str] = []
    while res.has_next():
        out.append(res.get_next()[0])
    return out


def test_patch_forward_compat_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Store written at 1.3.0 opens cleanly when running constant is 1.3.1."""
    db = tmp_path / "kg.kuzu"
    KGStore.open(db).close()  # writes the real current constant (1.3.0)

    monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.3.1")
    s = KGStore.open(db)
    try:
        # Stored row is left at 1.3.0; we do NOT silently rewrite it.
        assert _meta_rows(s) == ["1.3.0"]
    finally:
        s.close()


def test_minor_forward_compat_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Store written at 1.3.0 opens cleanly when running constant is 1.4.0."""
    db = tmp_path / "kg.kuzu"
    KGStore.open(db).close()

    monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.4.0")
    s = KGStore.open(db)
    try:
        assert _meta_rows(s) == ["1.3.0"]
    finally:
        s.close()


def test_patch_downgrade_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running 1.3.0 against a 1.3.1 store is a downgrade — must raise."""
    db = tmp_path / "kg.kuzu"
    # Write a 1.3.1 store first by bumping the constant for the create.
    monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.3.1")
    KGStore.open(db).close()

    monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.3.0")
    with pytest.raises(kg.SchemaVersionMismatch) as ei:
        KGStore.open(db)
    assert ei.value.stored == "1.3.1"
    assert ei.value.expected == "1.3.0"


def test_major_bump_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Major version bump on expected vs stored is incompatible."""
    db = tmp_path / "kg.kuzu"
    KGStore.open(db).close()  # 1.3.0

    monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "2.0.0")
    with pytest.raises(kg.SchemaVersionMismatch) as ei:
        KGStore.open(db)
    assert ei.value.expected == "2.0.0"
    assert ei.value.stored == "1.3.0"


def test_older_major_against_newer_store_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running an older major against a newer-major store is incompatible."""
    db = tmp_path / "kg.kuzu"
    monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "2.0.0")
    KGStore.open(db).close()

    monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "1.9.9")
    with pytest.raises(kg.SchemaVersionMismatch) as ei:
        KGStore.open(db)
    assert ei.value.stored == "2.0.0"
    assert ei.value.expected == "1.9.9"
