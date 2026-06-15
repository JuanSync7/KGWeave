"""v1.6-#3 G5: ``__all__`` list attached to PyModule payload."""
from __future__ import annotations

import json
from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "dunder_all.py"


def test_walker_records_dunder_all_on_module_payload() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    mod = nodes[0]
    assert mod.kind == "PyModule"
    assert mod.payload.get("all_exports") == ["alpha", "beta"]


def test_writer_roundtrips_dunder_all(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyModule'"
            " RETURN n.payload AS p",
        )
        payload = json.loads(res.rows[0]["p"])
        assert payload["payload"]["all_exports"] == ["alpha", "beta"]
    finally:
        store.close()
