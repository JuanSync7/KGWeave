"""v1.6-#3 G4: imports inside ``if TYPE_CHECKING:`` carry runtime=False."""
from __future__ import annotations

import json
from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "type_checking.py"


def test_walker_marks_type_checking_imports_runtime_false() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    by_primary = {n.name: n for n in nodes if n.kind == "PyImport"}
    # Regular runtime imports are flagged True (key always present).
    assert by_primary["sys"].payload.get("runtime") is True
    # Imports inside `if TYPE_CHECKING:` are flagged False.
    assert by_primary["collections"].payload.get("runtime") is False


def test_writer_roundtrips_runtime_flag(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyImport'"
            " AND n.name='collections' RETURN n.payload AS p",
        )
        payload = json.loads(res.rows[0]["p"])
        assert payload["payload"]["runtime"] is False
    finally:
        store.close()
