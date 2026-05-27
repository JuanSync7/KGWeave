"""PyScopeResolutionConnector — out-of-corpus star-imports are record-only (v1.13-#3).

When ``from external_not_in_corpus import *`` references a module that is
NOT in the corpus, the connector must:

* leave captures (e.g. ``some_external_name``) classified as
  ``unresolved``;
* emit NO ``cross-file-import`` entry for those captures (there is no
  origin module to point them at);
* still preserve the ``PyImport`` row produced by the walker, with
  ``is_star=True`` and ``module='external_not_in_corpus'``.

Pins existing connector behaviour — there is overlapping coverage in
``test_py_scope_resolution_star.py`` for the unresolved aspect, but this
file additionally pins the PyImport-row preservation and the
no-``cross-file-import`` invariant.
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


def _py_imports_for_origin(store, stem: str) -> list[dict]:
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
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyImport' "
        "  AND n.origin_id IN $oids "
        "RETURN n.payload AS p, n.start_offset AS s ORDER BY s",
        {"oids": oids},
    )
    out: list[dict] = []
    for row in res.rows:
        payload = json.loads(row["p"])
        inner = payload.get("payload", {})
        out.append(inner)
    return out


def test_out_of_corpus_star_import_capture_stays_unresolved(
    tmp_path: Path,
) -> None:
    """Capture of ``some_external_name`` must classify as ``unresolved``
    when the star-import origin module is not in the corpus.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="star-external-record-only",
            paths=[FIXTURE_DIR / "star_external_consumer.py"],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps_lists = _lambda_resolutions_for_origin(
            store, "star_external_consumer"
        )
        flat = [e for caps in caps_lists for e in caps]
        by_name = {e["name"]: e for e in flat}
        assert "some_external_name" in by_name, by_name
        assert (
            by_name["some_external_name"]["kind"] == "unresolved"
        ), by_name["some_external_name"]
    finally:
        store.close()


def test_out_of_corpus_star_import_emits_no_cross_file_import_row(
    tmp_path: Path,
) -> None:
    """No capture for ``some_external_name`` may carry kind
    ``cross-file-import`` — there is no in-corpus origin to point at.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="star-external-record-only",
            paths=[FIXTURE_DIR / "star_external_consumer.py"],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps_lists = _lambda_resolutions_for_origin(
            store, "star_external_consumer"
        )
        flat = [e for caps in caps_lists for e in caps]
        offending = [
            e
            for e in flat
            if e.get("name") == "some_external_name"
            and e.get("kind") == "cross-file-import"
        ]
        assert offending == [], offending
    finally:
        store.close()


def test_out_of_corpus_star_import_preserves_pyimport_row(
    tmp_path: Path,
) -> None:
    """The walker-emitted ``PyImport`` row must survive connector run:
    ``is_star=True`` and ``module='external_not_in_corpus'``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="star-external-record-only",
            paths=[FIXTURE_DIR / "star_external_consumer.py"],
        )
        run_connectors(store, only=["py-scope-resolution"])
        imports = _py_imports_for_origin(store, "star_external_consumer")
        star = [
            p
            for p in imports
            if p.get("module") == "external_not_in_corpus"
            and bool(p.get("is_star"))
        ]
        assert len(star) == 1, imports
    finally:
        store.close()
