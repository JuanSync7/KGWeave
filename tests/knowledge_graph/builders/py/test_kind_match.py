"""v1.6-#3 G7: PEP 634 ``match`` statement as PyMatchStatement kind."""
from __future__ import annotations

from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "match_case.py"


def test_walker_emits_pymatchstatement() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    matches = [n for n in nodes if n.kind == "PyMatchStatement"]
    assert matches, f"expected >=1 PyMatchStatement, got kinds={[n.kind for n in nodes]}"


def test_writer_roundtrips_pymatchstatement(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyMatchStatement'"
            " RETURN count(n) AS k",
        )
        k = int(next(iter(res.rows[0].values())))
        assert k >= 1
    finally:
        store.close()
