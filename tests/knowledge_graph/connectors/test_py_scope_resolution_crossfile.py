"""PyScopeResolutionConnector — cross-file capture resolution (v1.9-#3).

Extends the v1.8-#3 closed set from 4 → 5 values by lifting a capture
that would otherwise be ``unresolved`` to ``cross-file-import`` when:

* the consuming module carries a ``PyImport`` whose ``aliases`` payload
  maps ``local_name -> origin_module.canonical_name``, AND
* the origin module is present in the same corpus, AND
* the canonical (unaliased) name is a public top-level binding of that
  origin module (top-level PyFunction / PyClass / re-exported PyImport).

Star-imports (``from X import *``) stay ``unresolved`` — out of scope.

Negative path: an imported name whose origin module is NOT present in
the corpus also stays ``unresolved``.
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
    """Return ``captures_resolved`` for every PyLambda whose owning
    PyModule node has ``name == stem``."""
    # Find origin_id(s) via the PyModule row whose name matches stem.
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


def test_crossfile_import_capture_classified_as_cross_file_import(
    tmp_path: Path,
) -> None:
    """``foo`` in crossfile_capture_b is imported from crossfile_capture_a
    (both in corpus). Connector must tag it ``cross-file-import`` with
    ``origin_module == 'crossfile_capture_a'``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="crossfile",
            paths=[
                FIXTURE_DIR / "crossfile_capture_a.py",
                FIXTURE_DIR / "crossfile_capture_b.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        b_caps = _lambda_resolutions_for_origin(store, "crossfile_capture_b")
        assert len(b_caps) == 1
        entries = b_caps[0]
        # locate the ``foo`` entry
        by_name = {e["name"]: e for e in entries}
        assert "foo" in by_name, by_name
        foo_entry = by_name["foo"]
        assert foo_entry["kind"] == "cross-file-import", foo_entry
        assert foo_entry.get("origin_module") == "crossfile_capture_a", foo_entry
    finally:
        store.close()


def test_import_without_corpus_origin_stays_unresolved(tmp_path: Path) -> None:
    """``bar`` is imported from a module not in the corpus; resolution
    must stay ``unresolved`` and no ``origin_module`` field is added.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="crossfile-neg",
            paths=[FIXTURE_DIR / "crossfile_capture_external.py"],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps = _lambda_resolutions_for_origin(
            store, "crossfile_capture_external"
        )
        assert len(caps) == 1
        by_name = {e["name"]: e for e in caps[0]}
        assert "bar" in by_name, by_name
        bar_entry = by_name["bar"]
        assert bar_entry["kind"] == "unresolved", bar_entry
        assert "origin_module" not in bar_entry, bar_entry
    finally:
        store.close()
