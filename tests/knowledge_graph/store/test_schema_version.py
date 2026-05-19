"""``:Meta`` schema-version guard tests.

Covers the v1.2 forward-compat insurance: every store carries a single
``:Meta`` row recording the ``schema_version`` it was written with. On
re-open we assert it matches the running constant, otherwise raise a
typed :class:`SchemaVersionMismatch`. Stores predating the guard (no
``:Meta`` row) are auto-migrated on first reopen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_graph as kg
from knowledge_graph.store import KGStore
from knowledge_graph.store import schema as _schema_mod


def _meta_rows(store: KGStore) -> list[str]:
    res = store.conn.execute("MATCH (m:Meta) RETURN m.schema_version")
    out: list[str] = []
    while res.has_next():
        out.append(res.get_next()[0])
    return out


def test_first_open_writes_meta_row(tmp_path: Path) -> None:
    """A fresh store contains exactly one :Meta row at the current version."""
    db = tmp_path / "kg.kuzu"
    s = KGStore.open(db)
    try:
        rows = _meta_rows(s)
        assert rows == [_schema_mod.KGWEAVE_SCHEMA_VERSION]
    finally:
        s.close()


def test_second_open_is_idempotent(tmp_path: Path) -> None:
    """Re-opening the same store keeps a single :Meta row, no version drift."""
    db = tmp_path / "kg.kuzu"
    KGStore.open(db).close()
    s2 = KGStore.open(db)
    try:
        rows = _meta_rows(s2)
        assert rows == [_schema_mod.KGWEAVE_SCHEMA_VERSION]
    finally:
        s2.close()


def test_mismatch_raises_schema_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monkeypatch the constant after first-create; second open must raise."""
    db = tmp_path / "kg.kuzu"
    KGStore.open(db).close()

    monkeypatch.setattr(_schema_mod, "KGWEAVE_SCHEMA_VERSION", "99.0.0")

    with pytest.raises(kg.SchemaVersionMismatch) as ei:
        KGStore.open(db)
    exc = ei.value
    assert exc.expected == "99.0.0"
    # The stored version was the real pre-bump constant from the file.
    assert exc.stored is not None
    assert exc.stored != "99.0.0"


def test_legacy_store_auto_migrates(tmp_path: Path) -> None:
    """A store that pre-dates :Meta (table exists, no row) is migrated in-place."""
    db = tmp_path / "kg.kuzu"
    s = KGStore.open(db)
    # Simulate a legacy store: drop the Meta row but keep the table.
    s.conn.execute("MATCH (m:Meta) DELETE m")
    assert _meta_rows(s) == []
    s.close()

    s2 = KGStore.open(db)
    try:
        rows = _meta_rows(s2)
        assert rows == [_schema_mod.KGWEAVE_SCHEMA_VERSION]
    finally:
        s2.close()


def test_exception_reexported_from_facade() -> None:
    """``from knowledge_graph import SchemaVersionMismatch`` must work."""
    from knowledge_graph import SchemaVersionMismatch  # noqa: F401

    assert SchemaVersionMismatch.__name__ == "SchemaVersionMismatch"
    # And the exception carries typed stored/expected fields.
    e = SchemaVersionMismatch(stored="1.0.0", expected="1.2.0")
    assert e.stored == "1.0.0"
    assert e.expected == "1.2.0"


def test_open_store_facade_writes_meta(tmp_path: Path) -> None:
    """The public ``open_store`` entry point also writes the :Meta row."""
    db = tmp_path / "kg.kuzu"
    s = kg.open_store(db)
    try:
        rows = _meta_rows(s)
        assert rows == [_schema_mod.KGWEAVE_SCHEMA_VERSION]
    finally:
        s.close()


def test_version_constant_is_one_two_oh() -> None:
    """The current schema version is bumped to 1.2.0 as part of this change."""
    assert _schema_mod.KGWEAVE_SCHEMA_VERSION == "1.2.0"
