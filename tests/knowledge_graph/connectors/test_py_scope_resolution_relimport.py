"""PyScopeResolutionConnector — relative-import capture resolution (v1.10-#2).

v1.8-#1 walker convention records relative imports' canonical name with
leading dots verbatim (``from .sibling import foo`` -> ``.sibling.foo``).
v1.9-#3's ``module_exports`` index is keyed by absolute module qualname,
so the bare lookup misses. v1.10-#2 added a resolver that converts the
relative canonical into an absolute qualname using the consuming
module's qualname, then plugs it into both the v1.9-#3
``cross-file-import`` lift AND the v1.10-#1 ``module-import`` lift.

Since v1.11-#1, ``PyModule.name`` is package-qualified — both
``relimport_pkg.consumer`` and ``relimport_pkg.sibling`` are the
qualnames here (their parents contain ``__init__.py``).

Positive: ``relimport_pkg.consumer`` does ``from .sibling import foo``
and captures ``foo`` in a lambda. The resolved canonical is
``relimport_pkg.sibling.foo``. The capture must classify as
``cross-file-import`` with ``origin_module == "relimport_pkg.sibling"``.

Negative: ``relimport_escape_pkg.escape_consumer`` does
``from ..outside import foo``. With qualname depth 2 (the package
chain) and 2 leading dots, the resolver lands on an empty package +
body ``outside.foo``. That falls through to ``cross-file-import``
lookup which misses (``outside`` is not corpus-resident) and the
capture stays ``unresolved`` with no ``origin_module``.
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


def _lambda_resolutions_for_origin(store, module_name: str) -> list[list[dict]]:
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


def test_relative_import_capture_classified_as_cross_file_import(
    tmp_path: Path,
) -> None:
    """``from .sibling import foo`` in consumer.py must resolve to the
    sibling module's qualname (``relimport_pkg.sibling`` since v1.11-#1)
    and lift to ``cross-file-import`` with
    ``origin_module == "relimport_pkg.sibling"``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="relimport-pos",
            paths=[
                FIXTURE_DIR / "relimport_pkg" / "__init__.py",
                FIXTURE_DIR / "relimport_pkg" / "sibling.py",
                FIXTURE_DIR / "relimport_pkg" / "consumer.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps = _lambda_resolutions_for_origin(store, "relimport_pkg.consumer")
        assert len(caps) == 1, caps
        by_name = {e["name"]: e for e in caps[0]}
        assert "foo" in by_name, by_name
        entry = by_name["foo"]
        assert entry["kind"] == "cross-file-import", entry
        assert entry.get("origin_module") == "relimport_pkg.sibling", entry
    finally:
        store.close()


def test_relative_import_escape_above_package_stays_unresolved(
    tmp_path: Path,
) -> None:
    """``from ..outside import foo`` from a 2-segment consuming qualname
    (``relimport_escape_pkg.escape_consumer`` since v1.11-#1) lands on
    an empty package + body ``outside.foo``. The lift then misses
    because ``outside`` is not a corpus-resident module, and the
    capture must stay ``unresolved`` with no ``origin_module``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="relimport-escape",
            paths=[
                FIXTURE_DIR / "relimport_escape_pkg" / "__init__.py",
                FIXTURE_DIR / "relimport_escape_pkg" / "escape_consumer.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps = _lambda_resolutions_for_origin(
            store, "relimport_escape_pkg.escape_consumer"
        )
        assert len(caps) == 1, caps
        by_name = {e["name"]: e for e in caps[0]}
        assert "foo" in by_name, by_name
        entry = by_name["foo"]
        assert entry["kind"] == "unresolved", entry
        assert "origin_module" not in entry, entry
    finally:
        store.close()
