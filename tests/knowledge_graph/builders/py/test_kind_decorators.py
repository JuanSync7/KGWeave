"""v1.6-#3 G1: decorators on functions and classes.

Walker must record decorators on the decorated PyFunction / PyClass
node under ``payload['decorators']`` as a list of source-text strings
in outer-most-first order. Writer must round-trip them through the
JSON ``payload`` column.
"""
from __future__ import annotations

import json
from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "decorators.py"


def test_walker_records_decorators_on_functions_and_classes() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    by_name = {n.name: n for n in nodes if n.kind in {"PyFunction", "PyClass"}}

    assert by_name["plain_decorated"].payload.get("decorators") == ["trace"]

    decs = by_name["parametrised_decorated"].payload.get("decorators") or []
    assert decs and decs[0].startswith("functools.lru_cache")

    assert by_name["value"].payload.get("decorators") == ["property"]
    assert by_name["helper"].payload.get("decorators") == ["staticmethod"]
    assert by_name["make"].payload.get("decorators") == ["classmethod"]

    assert by_name["Decorated"].payload.get("decorators") == ["trace"]


def test_writer_roundtrips_decorator_payload(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.name='plain_decorated'"
            " RETURN n.payload AS p",
        )
        payload = json.loads(res.rows[0]["p"])
        assert payload["payload"]["decorators"] == ["trace"]

        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyClass'"
            " AND n.name='Decorated' RETURN n.payload AS p",
        )
        payload = json.loads(res.rows[0]["p"])
        assert payload["payload"]["decorators"] == ["trace"]
    finally:
        store.close()
