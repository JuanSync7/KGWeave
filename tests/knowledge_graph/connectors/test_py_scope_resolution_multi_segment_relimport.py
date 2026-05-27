"""PyScopeResolutionConnector — multi-segment relative-import resolution
(v1.11-#3).

v1.10-#2's ``_resolve_relative_qualname`` already does the dot-segment
math correctly. v1.11-#1 made ``PyModule.name`` package-qualified.
Together, multi-segment relative imports across package depth now
resolve end-to-end.

Fixture: ``qual_pkg.sub.consumer`` (3-segment qualname) does:

* ``from .mod import foo`` (1 dot) -> must resolve to
  ``qual_pkg.sub.mod`` (the v1.11-#1 leaf fixture).
* ``from ..mod import foo as top_foo`` (2 dots) -> must resolve to
  ``qual_pkg.mod`` (the new sibling of ``sub/``).

Both bindings are captured in lambdas; the captures must classify as
``cross-file-import`` with the FULL qualified ``origin_module``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_graph import (
    cypher,
    extract,
    open_store,
    register_connector,
    run_connectors,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "py"


@pytest.fixture(scope="module", autouse=True)
def _register_py_scope_resolution_connector() -> None:
    from knowledge_graph.connectors.py_scope_resolution import (
        PyScopeResolutionConnector,
    )

    register_connector(PyScopeResolutionConnector())


def _lambda_captures_for_module(store, module_name: str) -> list[list[dict]]:
    mod_res = cypher(
        store,
        "MATCH (m:Node) WHERE m.source='py' AND m.kind='PyModule' "
        "  AND m.name=$mname RETURN m.origin_id AS oid",
        {"mname": module_name},
    )
    oids = [row["oid"] for row in mod_res.rows]
    if not oids:
        return []
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyLambda' "
        "  AND n.origin_id IN $oids "
        "RETURN n.payload AS p, n.start_offset AS s ORDER BY s",
        {"oids": oids},
    )
    out: list[list[dict]] = []
    for row in res.rows:
        payload = json.loads(row["p"])
        inner = payload.get("payload", {})
        out.append(inner.get("captures_resolved", []))
    return out


def test_one_dot_relimport_resolves_to_full_qualname(tmp_path: Path) -> None:
    """``from .mod import foo`` in ``qual_pkg.sub.consumer`` -> capture of
    ``foo`` classifies as ``cross-file-import`` with
    ``origin_module == "qual_pkg.sub.mod"``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="qualreli-1dot",
            paths=[
                FIXTURE_DIR / "qual_pkg" / "__init__.py",
                FIXTURE_DIR / "qual_pkg" / "mod.py",
                FIXTURE_DIR / "qual_pkg" / "sub" / "__init__.py",
                FIXTURE_DIR / "qual_pkg" / "sub" / "mod.py",
                FIXTURE_DIR / "qual_pkg" / "sub" / "consumer.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps = _lambda_captures_for_module(store, "qual_pkg.sub.consumer")
        assert len(caps) >= 1, caps
        # First lambda binds `foo` (1-dot relimport target).
        by_name = {e["name"]: e for e in caps[0]}
        assert "foo" in by_name, by_name
        entry = by_name["foo"]
        assert entry["kind"] == "cross-file-import", entry
        assert entry.get("origin_module") == "qual_pkg.sub.mod", entry
    finally:
        store.close()


def test_two_dot_relimport_resolves_to_parent_package(tmp_path: Path) -> None:
    """``from ..mod import foo as top_foo`` in ``qual_pkg.sub.consumer``
    -> capture of ``top_foo`` classifies as ``cross-file-import`` with
    ``origin_module == "qual_pkg.mod"``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="qualreli-2dot",
            paths=[
                FIXTURE_DIR / "qual_pkg" / "__init__.py",
                FIXTURE_DIR / "qual_pkg" / "mod.py",
                FIXTURE_DIR / "qual_pkg" / "sub" / "__init__.py",
                FIXTURE_DIR / "qual_pkg" / "sub" / "mod.py",
                FIXTURE_DIR / "qual_pkg" / "sub" / "consumer.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps = _lambda_captures_for_module(store, "qual_pkg.sub.consumer")
        assert len(caps) >= 2, caps
        # Second lambda binds `top_foo` (2-dot relimport target).
        by_name = {e["name"]: e for e in caps[1]}
        assert "top_foo" in by_name, by_name
        entry = by_name["top_foo"]
        assert entry["kind"] == "cross-file-import", entry
        assert entry.get("origin_module") == "qual_pkg.mod", entry
    finally:
        store.close()
