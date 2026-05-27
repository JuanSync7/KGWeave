"""v1.13-#4 — namespace package with nested subpackages.

Closes the gap left by v1.12-#2's leaf/container split: a directory
with BOTH ``.py`` files AND subdirectories (none with ``__init__.py``)
must still participate in the namespace walk.

Fixture tree (no ``__init__.py`` anywhere)::

    ns_nested/
      sub/
        mod.py          # → ns_nested.sub.mod
        inner/
          mod2.py       # → ns_nested.sub.inner.mod2

Non-regression: flat fixture-bucket files (e.g. ``module_capture_a.py``)
must continue to receive stem-only qualnames — the walk must STOP at
``fixtures/py/`` rather than ascending into ``fixtures/`` or beyond.
"""

from __future__ import annotations

from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


def _module_names(store) -> set[str]:
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyModule' "
        "RETURN n.name AS name",
    )
    return {row["name"] for row in res.rows}


def test_ns_nested_mixed_dir_qualname(tmp_path: Path) -> None:
    """Mixed dir (``.py`` + subdir, no ``__init__.py``) participates."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="nsn",
            paths=[
                FIXTURE_DIR / "ns_nested" / "sub" / "mod.py",
                FIXTURE_DIR / "ns_nested" / "sub" / "inner" / "mod2.py",
            ],
        )
        names = _module_names(store)
        assert "ns_nested.sub.mod" in names, names
        assert "ns_nested.sub.inner.mod2" in names, names
    finally:
        store.close()


def test_ns_nested_flat_bucket_non_regression(tmp_path: Path) -> None:
    """Flat fixture-bucket ``.py`` files must keep stem-only qualnames.

    ``fixtures/py/`` contains both ``.py`` files AND subdirectories so
    under a naive "any dir without ``__init__.py`` and any ``.py``
    participates" rule it would itself be a namespace participant —
    the corpus-root stop must prevent that.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="flat",
            paths=[FIXTURE_DIR / "module_capture_a.py"],
        )
        names = _module_names(store)
        assert "module_capture_a" in names, names
        # No name should include "py." (the bucket dir) or "fixtures."
        bad = {n for n in names if "py." in n or "fixtures." in n}
        assert not bad, bad
    finally:
        store.close()
