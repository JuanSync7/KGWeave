"""PyScopeResolutionConnector — guarded star-imports do not expand (v1.12-#3).

When a ``from X import *`` is wrapped in a non-runtime guard (e.g.
``if TYPE_CHECKING:`` or ``try: ... except ImportError:``), the v1.10-#3
expansion logic must SKIP the expansion. Captures that would have lifted
to ``cross-file-import`` under an unguarded star-import must instead
stay ``unresolved``.

Regression: the unguarded ``star_consumer`` case still lifts (covered by
``test_py_scope_resolution_star.py``).
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


def test_star_import_under_type_checking_does_not_expand(tmp_path: Path) -> None:
    """``from star_target import *`` under ``if TYPE_CHECKING:`` must NOT
    contribute to runtime cross-file resolution. Capturing ``foo`` stays
    ``unresolved``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="star-type-checking",
            paths=[
                FIXTURE_DIR / "star_target.py",
                FIXTURE_DIR / "star_type_checking.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps_lists = _lambda_resolutions_for_origin(
            store, "star_type_checking"
        )
        flat = [e for caps in caps_lists for e in caps]
        by_name = {e["name"]: e for e in flat}
        assert "foo" in by_name, by_name
        assert by_name["foo"]["kind"] == "unresolved", by_name["foo"]
        assert "origin_module" not in by_name["foo"], by_name["foo"]
    finally:
        store.close()


def test_star_import_under_try_import_does_not_expand(tmp_path: Path) -> None:
    """``from star_target import *`` under ``try / except ImportError`` is
    guarded against import failure; the connector must NOT expand it.
    Capturing ``foo`` stays ``unresolved``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="star-try-import",
            paths=[
                FIXTURE_DIR / "star_target.py",
                FIXTURE_DIR / "star_try_import.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps_lists = _lambda_resolutions_for_origin(store, "star_try_import")
        flat = [e for caps in caps_lists for e in caps]
        by_name = {e["name"]: e for e in flat}
        assert "foo" in by_name, by_name
        assert by_name["foo"]["kind"] == "unresolved", by_name["foo"]
        assert "origin_module" not in by_name["foo"], by_name["foo"]
    finally:
        store.close()
