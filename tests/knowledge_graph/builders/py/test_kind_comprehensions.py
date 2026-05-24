"""v1.6-#3 G9: comprehension scopes as PyComprehension kind.

List / set / dict / generator comprehensions are scope-creating
constructs in Python 3, so the walker emits a PyComprehension per
occurrence so that connectors can resolve the inner names later.
"""
from __future__ import annotations

from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "comprehensions.py"


def test_walker_emits_pycomprehension_per_form() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    comps = [n for n in nodes if n.kind == "PyComprehension"]
    # 4 forms in the fixture (list, set, dict, generator).
    assert len(comps) == 4, f"expected 4 PyComprehension, got {len(comps)}: {[n.payload for n in comps]}"
    forms = {n.payload.get("form") for n in comps}
    assert forms == {"list", "set", "dict", "generator"}


def test_writer_roundtrips_pycomprehension(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyComprehension'"
            " RETURN count(n) AS k",
        )
        k = int(next(iter(res.rows[0].values())))
        assert k == 4
    finally:
        store.close()
