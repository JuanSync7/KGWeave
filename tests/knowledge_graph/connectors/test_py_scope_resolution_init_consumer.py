"""PyScopeResolutionConnector — ``__init__.py``-consumer relative-import
edge (v1.13-#1).

A relative import inside ``pkg/__init__.py`` has the consuming module's
qualname literally equal to the package qualname (``pkg``), NOT a leaf
inside it. v1.12-#1's resolver applied the ``N - K`` formula uniformly
which gave the wrong answer for this shape: ``from . import sibling``
inside ``pkg/__init__.py`` (N=1, K=1, body=``sibling``) collapsed to
``sibling`` (top-level) instead of ``pkg.sibling``.

v1.13-#1 threads ``is_init_module`` through the resolver. When True the
effective dot count is ``K - 1``, so ``from . import sibling`` inside
``init_consumer_pkg/__init__.py`` resolves to
``init_consumer_pkg.sibling`` — a corpus-resident module qualname —
which the v1.10-#1 ``module-import`` lift then promotes.

The lambda in ``__init__.py`` captures the sibling module object, so
the closed-set kind is ``module-import`` (per the v1.10-#1 disjoint
lifts: ``from . import sibling`` binds the *module*; ``from .sibling
import foo`` would bind the *member* and be ``cross-file-import``).
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


def test_init_consumer_module_import_capture_resolves_to_pkg_sibling(
    tmp_path: Path,
) -> None:
    """``from . import sibling`` inside ``init_consumer_pkg/__init__.py``
    must resolve the captured ``sibling`` module name to the corpus
    qualname ``init_consumer_pkg.sibling`` and lift to ``module-import``.
    Pre-v1.13-#1 the resolver collapsed it to ``sibling`` (top-level)
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
        assert "sibling" in by_name, by_name
        entry = by_name["sibling"]
        assert entry["kind"] == "module-import", entry
        assert (
            entry.get("origin_module") == "init_consumer_pkg.sibling"
        ), entry
    finally:
        store.close()
