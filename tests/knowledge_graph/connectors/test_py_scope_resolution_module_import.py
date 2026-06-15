"""PyScopeResolutionConnector — module-import capture resolution (v1.10-#1).

Widens the v1.9-#3 closed set from 5 -> 6 by lifting a capture whose
local was bound by ``import X`` / ``import X.Y`` (NOT
``from X import name``) to ``module-import`` when ``X`` (or ``X.Y``) is
itself a corpus-resident module qualname. The resolved entry also
carries ``origin_module: <qualname>``.

Out-of-corpus module imports (e.g. ``import json``) stay ``unresolved``
— negative path covered by the same fixture.

v1.9-#3 ``from X import name`` lifts (``cross-file-import``) must NOT
trigger for ``import X`` shapes — guarded by the closed-set fan-out
test below.
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


def _lambda_resolutions_for_origin(store, stem: str) -> list[list[dict]]:
    mod_res = cypher(
        store,
        "MATCH (m:Node) WHERE m.source='py' AND m.kind='PyModule' "
        "  AND m.name=$stem RETURN m.origin_id AS oid",
        {"stem": stem},
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


def test_corpus_module_import_capture_classified_as_module_import(
    tmp_path: Path,
) -> None:
    """``module_capture_a`` captured in a lambda inside ``module_capture_b``
    resolves to ``module-import`` with ``origin_module ==
    'module_capture_a'`` when both files are in the corpus.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="module-import",
            paths=[
                FIXTURE_DIR / "module_capture_a.py",
                FIXTURE_DIR / "module_capture_b.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        b_caps = _lambda_resolutions_for_origin(store, "module_capture_b")
        assert len(b_caps) == 1
        by_name = {e["name"]: e for e in b_caps[0]}
        assert "module_capture_a" in by_name, by_name
        entry = by_name["module_capture_a"]
        assert entry["kind"] == "module-import", entry
        assert entry.get("origin_module") == "module_capture_a", entry


    finally:
        store.close()


def test_out_of_corpus_module_import_capture_stays_unresolved(
    tmp_path: Path,
) -> None:
    """``json`` is imported but is NOT in the corpus we feed to the
    connector. The captured module object must stay ``unresolved`` with
    no ``origin_module`` field — the lift fires only for corpus-resident
    module qualnames.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="module-import-neg",
            paths=[
                FIXTURE_DIR / "module_capture_a.py",
                FIXTURE_DIR / "module_capture_b.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        b_caps = _lambda_resolutions_for_origin(store, "module_capture_b")
        assert len(b_caps) == 1
        by_name = {e["name"]: e for e in b_caps[0]}
        assert "json" in by_name, by_name
        entry = by_name["json"]
        assert entry["kind"] == "unresolved", entry
        assert "origin_module" not in entry, entry
    finally:
        store.close()


def test_module_import_not_misclassified_as_cross_file_import(
    tmp_path: Path,
) -> None:
    """Regression guard: ``import X`` captures must NOT be lifted to
    ``cross-file-import`` (that kind is reserved for ``from X import
    name`` shapes per v1.9-#3). The two lifts are disjoint.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="module-import-disjoint",
            paths=[
                FIXTURE_DIR / "module_capture_a.py",
                FIXTURE_DIR / "module_capture_b.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        b_caps = _lambda_resolutions_for_origin(store, "module_capture_b")
        assert len(b_caps) == 1
        kinds = {e["name"]: e["kind"] for e in b_caps[0]}
        assert kinds.get("module_capture_a") != "cross-file-import", kinds
    finally:
        store.close()
