"""v1.11-#1 — Package-qualified ``PyModule.name``.

The writer must derive ``PyModule.name`` by walking up parent directories
that contain ``__init__.py``: the qualname is the dot-joined chain from
the outermost-package-with-init down to (and including) the file's stem.

Positive: a 3-level package fixture (``qual_pkg/sub/mod.py``) must
produce qualnames ``qual_pkg``, ``qual_pkg.sub``, and ``qual_pkg.sub.mod``.

Negative: a top-level fixture with no sibling ``__init__.py``
(``star_target.py``) must keep the existing stem-only name.
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


def test_package_qualname_for_nested_module(tmp_path: Path) -> None:
    """``qual_pkg/sub/mod.py`` must produce ``PyModule.name`` for the
    leaf as the dot-joined ancestor-package chain plus its file stem."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="qual",
            paths=[
                FIXTURE_DIR / "qual_pkg" / "__init__.py",
                FIXTURE_DIR / "qual_pkg" / "sub" / "__init__.py",
                FIXTURE_DIR / "qual_pkg" / "sub" / "mod.py",
            ],
        )
        names = _module_names(store)
        assert "qual_pkg" in names, names
        assert "qual_pkg.sub" in names, names
        assert "qual_pkg.sub.mod" in names, names
    finally:
        store.close()


def test_top_level_module_keeps_stem_only_name(tmp_path: Path) -> None:
    """A top-level fixture with no sibling ``__init__.py`` must keep the
    pre-v1.11 behaviour: ``PyModule.name == Path(uri).stem``."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="top",
            paths=[FIXTURE_DIR / "star_target.py"],
        )
        names = _module_names(store)
        assert names == {"star_target"}, names
    finally:
        store.close()
