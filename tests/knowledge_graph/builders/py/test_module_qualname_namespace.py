"""v1.12-#2 — PEP 420 namespace-package-qualified ``PyModule.name``.

The walker's qualname-walk was widened to handle namespace packages
(PEP 420 — no ``__init__.py``). A namespace-walk continues up through
ancestors that have NO ``__init__.py`` AND NO direct ``.py`` files
(pure namespace-container directories). The walk terminates at the
first ancestor that breaks both rules.

The leaf parent of the file (which DOES contain ``.py`` siblings) is
included only if its OWN parent qualifies as a namespace container —
this distinguishes ``ns_pkg/sub/`` (parent ``ns_pkg/`` has no direct
``.py``, so include) from ``fixtures/py/`` (parent ``fixtures/`` has
a direct ``__init__.py``, so DO NOT include — stem fallback).
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


def test_namespace_package_qualname_for_nested_module(tmp_path: Path) -> None:
    """``ns_pkg/sub/mod.py`` (no ``__init__.py`` anywhere in the chain)
    must produce ``PyModule.name == 'ns_pkg.sub.mod'``. Its sibling
    ``ns_pkg/sub/consumer.py`` must be ``ns_pkg.sub.consumer``."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="ns",
            paths=[
                FIXTURE_DIR / "ns_pkg" / "sub" / "mod.py",
                FIXTURE_DIR / "ns_pkg" / "sub" / "consumer.py",
            ],
        )
        names = _module_names(store)
        assert "ns_pkg.sub.mod" in names, names
        assert "ns_pkg.sub.consumer" in names, names
    finally:
        store.close()
