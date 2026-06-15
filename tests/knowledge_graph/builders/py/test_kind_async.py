"""v1.6-#3 G2: async def is PyFunction with is_async flag.

Charter mandates we DON'T introduce a separate PyAsyncFunction kind —
async-ness lives as a payload flag so downstream consumers can filter
without learning a new node type.
"""
from __future__ import annotations

import json
from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "async_defs.py"


def test_walker_marks_async_def_with_is_async_flag() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    fns = {n.name: n for n in nodes if n.kind == "PyFunction"}
    assert "fetch" in fns
    assert fns["fetch"].payload.get("is_async") is True
    assert "compute" in fns
    assert fns["compute"].payload.get("is_async", False) is False


def test_writer_roundtrips_is_async_flag(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.name='fetch'"
            " RETURN n.payload AS p",
        )
        payload = json.loads(res.rows[0]["p"])
        assert payload["payload"]["is_async"] is True
    finally:
        store.close()
