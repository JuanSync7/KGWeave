"""v1.14-#3 — classic package above a namespace ancestor.

Pins the regime-transition boundary: the classic walk (driven by
``__init__.py`` presence) terminates at the first ancestor that lacks
``__init__.py``. A namespace ancestor sitting ABOVE a classic package
is NOT consumed — the namespace walk only kicks in for files whose
*immediate* parent has no ``__init__.py``.

Fixture tree::

    mid_chain/               # no __init__.py
      ns_outer/              # no __init__.py (namespace dir)
        pkg_inner/
          __init__.py        # classic package starts here
          mod.py

Expected qualnames:
  - ``pkg_inner/__init__.py`` → ``pkg_inner``
  - ``pkg_inner/mod.py``       → ``pkg_inner.mod`` (NOT
    ``ns_outer.pkg_inner.mod``, NOT
    ``mid_chain.ns_outer.pkg_inner.mod``)
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


def test_mid_chain_classic_pkg_above_namespace(tmp_path: Path) -> None:
    """Classic walk stops at first missing ``__init__.py`` going up."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="midc",
            paths=[
                FIXTURE_DIR / "mid_chain" / "ns_outer" / "pkg_inner" / "__init__.py",
                FIXTURE_DIR / "mid_chain" / "ns_outer" / "pkg_inner" / "mod.py",
            ],
        )
        names = _module_names(store)
        assert "pkg_inner.mod" in names, names
        assert "pkg_inner" in names, names
        # The namespace ancestor must NOT be consumed by the classic walk.
        assert "ns_outer.pkg_inner.mod" not in names, names
        assert "mid_chain.ns_outer.pkg_inner.mod" not in names, names
        assert "ns_outer.pkg_inner" not in names, names
    finally:
        store.close()
