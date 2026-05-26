"""PyScopeResolutionConnector — star-import cross-file expansion (v1.10-#3).

When the consuming module does ``from X import *`` and ``X`` is a
corpus-resident module, the connector expands the star-import into the
origin module's public exports:

* If ``X`` has ``__all__``, only names in ``__all__`` flow through.
* Otherwise, every public top-level binding (NOT starting with ``_``)
  flows through.

Names that flow through classify as ``cross-file-import`` with the
correct ``origin_module``; names that are filtered out (underscore /
not in ``__all__``) stay ``unresolved``. Star-imports from modules NOT
in the corpus produce no new entries.
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


def test_star_import_public_name_lifts_to_cross_file_import(
    tmp_path: Path,
) -> None:
    """``foo`` is a public top-level binding of ``star_target``. The
    consumer's ``from star_target import *`` should make capturing
    ``foo`` resolve as ``cross-file-import`` with the right origin.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="star",
            paths=[
                FIXTURE_DIR / "star_target.py",
                FIXTURE_DIR / "star_consumer.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps_lists = _lambda_resolutions_for_origin(store, "star_consumer")
        flat = [e for caps in caps_lists for e in caps]
        by_name = {e["name"]: e for e in flat}
        assert "foo" in by_name, by_name
        assert by_name["foo"]["kind"] == "cross-file-import", by_name["foo"]
        assert by_name["foo"].get("origin_module") == "star_target", by_name["foo"]
    finally:
        store.close()


def test_star_import_underscore_name_stays_unresolved(tmp_path: Path) -> None:
    """``_private`` is an underscore binding of ``star_target``; PEP 8
    public-export rules (no ``__all__``) filter it out, so capturing it
    in the consumer stays ``unresolved``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="star-underscore",
            paths=[
                FIXTURE_DIR / "star_target.py",
                FIXTURE_DIR / "star_consumer.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps_lists = _lambda_resolutions_for_origin(store, "star_consumer")
        flat = [e for caps in caps_lists for e in caps]
        by_name = {e["name"]: e for e in flat}
        assert "_private" in by_name, by_name
        assert by_name["_private"]["kind"] == "unresolved", by_name["_private"]
        assert "origin_module" not in by_name["_private"], by_name["_private"]
    finally:
        store.close()


def test_star_import_honours_dunder_all(tmp_path: Path) -> None:
    """``star_target_all`` declares ``__all__ = ["bar"]``. Capturing
    ``bar`` in the consumer must lift to ``cross-file-import``; capturing
    ``baz`` (defined but excluded from ``__all__``) must stay
    ``unresolved``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="star-all",
            paths=[
                FIXTURE_DIR / "star_target_all.py",
                FIXTURE_DIR / "star_consumer_all.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps_lists = _lambda_resolutions_for_origin(
            store, "star_consumer_all"
        )
        flat = [e for caps in caps_lists for e in caps]
        by_name = {e["name"]: e for e in flat}
        assert "bar" in by_name, by_name
        assert by_name["bar"]["kind"] == "cross-file-import", by_name["bar"]
        assert (
            by_name["bar"].get("origin_module") == "star_target_all"
        ), by_name["bar"]
        assert "baz" in by_name, by_name
        assert by_name["baz"]["kind"] == "unresolved", by_name["baz"]
        assert "origin_module" not in by_name["baz"], by_name["baz"]
    finally:
        store.close()


def test_star_import_from_out_of_corpus_module_stays_unresolved(
    tmp_path: Path,
) -> None:
    """When the star-import's origin module is NOT in the corpus, no
    entries should flow through — every capture stays ``unresolved``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        # Only the consumer is in the corpus; star_target is absent.
        extract(
            store,
            source="py",
            corpus="star-external",
            paths=[FIXTURE_DIR / "star_consumer.py"],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps_lists = _lambda_resolutions_for_origin(store, "star_consumer")
        flat = [e for caps in caps_lists for e in caps]
        by_name = {e["name"]: e for e in flat}
        assert "foo" in by_name, by_name
        assert by_name["foo"]["kind"] == "unresolved", by_name["foo"]
        assert "origin_module" not in by_name["foo"], by_name["foo"]
    finally:
        store.close()
