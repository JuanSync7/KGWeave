"""v1.9-#1: PyScopeResolutionConnector classifies PyComprehension.captures.

The walker now emits ``captures: list[str]`` on every PyComprehension
payload (v1.9-#1 walker half). This test asserts the connector
parametrises its scope indexer over comprehensions as well as lambdas
and writes ``captures_resolved`` with the same closed kind set:

    {"local-in-enclosing", "module-level", "builtin", "unresolved"}
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
FIXTURE = "comprehension_captures.py"


@pytest.fixture(scope="module", autouse=True)
def _register_py_scope_resolution_connector() -> None:
    from knowledge_graph.connectors.py_scope_resolution import (
        PyScopeResolutionConnector,
    )

    register_connector(PyScopeResolutionConnector())


def _all_comp_resolutions(store) -> list[list[dict]]:
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyComprehension' "
        "RETURN n.payload AS p, n.start_offset AS s ORDER BY s",
        {},
    )
    out: list[list[dict]] = []
    for row in res.rows:
        payload = json.loads(row["p"])
        inner = payload.get("payload", {})
        out.append(inner.get("captures_resolved", []))
    return out


def _by_name(entries: list[dict]) -> dict[str, str]:
    return {e["name"]: e["kind"] for e in entries}


def test_comprehension_captures_resolved_covers_all_four_kinds(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="scoperes",
            paths=[FIXTURE_DIR / FIXTURE],
        )
        run_connectors(store, only=["py-scope-resolution"])
        all_caps = _all_comp_resolutions(store)
        assert len(all_caps) == 1, all_caps
        mapping = _by_name(all_caps[0])
        # Closed-set classifications from the fixture.
        assert mapping["y"] == "local-in-enclosing"
        assert mapping["OFFSET"] == "module-level"
        assert mapping["len"] == "builtin"
        assert mapping["range"] == "builtin"
        assert mapping["str"] == "builtin"
        assert mapping["mystery"] == "unresolved"
        # All four kinds must show up.
        kinds = set(mapping.values())
        assert kinds == {
            "local-in-enclosing",
            "module-level",
            "builtin",
            "unresolved",
        }, kinds
    finally:
        store.close()
