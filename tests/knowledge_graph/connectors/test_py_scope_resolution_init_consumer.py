"""PyScopeResolutionConnector — ``__init__.py``-consumer relative-import
edge (v1.13-#1).

A relative import inside ``pkg/__init__.py`` has the consuming module's
qualname literally equal to the package qualname (``pkg``), NOT a leaf
inside it. v1.12-#1's resolver applied the ``N - K`` formula uniformly
which gave the wrong answer for this shape: ``from .sibling import
foo`` inside ``pkg/__init__.py`` (consumer qualname ``pkg``, N=1,
canonical ``.sibling.foo``, K=1) retained ``N - K = 0`` segments and
resolved to top-level ``sibling.foo`` — which misses the corpus
module ``pkg.sibling``.

v1.13-#1 threads ``is_init_module`` through the resolver. When True
the effective dot count is ``K - 1``, so ``from .sibling import foo``
inside ``init_consumer_pkg/__init__.py`` resolves to
``init_consumer_pkg.sibling.foo``, the v1.10-#2 dotted split picks off
the leaf, and the v1.9-#3 cross-file lift promotes the capture.
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


def test_init_consumer_cross_file_capture_resolves_to_pkg_sibling(
    tmp_path: Path,
) -> None:
    """``from .sibling import foo`` inside ``init_consumer_pkg/__init__.py``
    must resolve the captured ``foo`` to the corpus member
    ``init_consumer_pkg.sibling.foo`` and lift to ``cross-file-import``.
    Pre-v1.13-#1 the resolver collapsed it to top-level ``sibling.foo``
    and the lift missed, leaving the capture ``unresolved``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="init-consumer",
            paths=[
                FIXTURE_DIR / "init_consumer_pkg" / "__init__.py",
                FIXTURE_DIR / "init_consumer_pkg" / "sibling.py",
            ],
        )
        run_connectors(store, only=["py-scope-resolution"])
        caps = _lambda_resolutions_for_origin(store, "init_consumer_pkg")
        assert len(caps) == 1, caps
        by_name = {e["name"]: e for e in caps[0]}
        assert "foo" in by_name, by_name
        entry = by_name["foo"]
        assert entry["kind"] == "cross-file-import", entry
        assert (
            entry.get("origin_module") == "init_consumer_pkg.sibling"
        ), entry
    finally:
        store.close()
