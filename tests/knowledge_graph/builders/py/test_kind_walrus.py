"""v1.6-#3 G8: walrus (PEP 572) flagged on enclosing PyFunction.

The charter wording is "flag on the enclosing assignment"; in
practice the most useful aggregation level is the enclosing function
node, which is the smallest stable identity for downstream tooling.
"""
from __future__ import annotations

import json
from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "walrus.py"


def test_walker_flags_walrus_on_enclosing_function() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    by_name = {n.name: n for n in nodes if n.kind == "PyFunction"}
    assert by_name["with_walrus"].payload.get("has_walrus") is True
    assert by_name["no_walrus"].payload.get("has_walrus") is False


def test_writer_roundtrips_has_walrus(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.name='with_walrus'"
            " RETURN n.payload AS p",
        )
        payload = json.loads(res.rows[0]["p"])
        assert payload["payload"]["has_walrus"] is True
    finally:
        store.close()
