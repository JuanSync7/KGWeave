"""PyScopeResolutionConnector — PEP 420 namespace-package relative-import
resolution (v1.12-#2).

Fixture: ``ns_pkg/sub/consumer.py`` (no ``__init__.py`` anywhere) does
``from .mod import foo``. With v1.12-#2's widened qualname-walk the
consumer's qualname is ``ns_pkg.sub.consumer`` and the resolver must
land the lambda capture on ``ns_pkg.sub.mod``.
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


def test_namespace_pkg_relimport_resolves_to_full_qualname(
    tmp_path: Path,
) -> None:
    """``from .mod import foo`` in ``ns_pkg.sub.consumer`` (no
    ``__init__.py`` anywhere) -> capture of ``foo`` classifies as
    ``cross-file-import`` with ``origin_module == "ns_pkg.sub.mod"``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="ns-1dot",
            paths=[
                FIXTURE_DIR / "ns_pkg" / "sub" / "mod.py",
                FIXTURE_DIR / "ns_pkg" / "sub" / "consumer.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps = _lambda_captures_for_module(store, "ns_pkg.sub.consumer")
        assert len(caps) >= 1, caps
        by_name = {e["name"]: e for e in caps[0]}
        assert "foo" in by_name, by_name
        entry = by_name["foo"]
        assert entry["kind"] == "cross-file-import", entry
        assert entry.get("origin_module") == "ns_pkg.sub.mod", entry
    finally:
        store.close()
