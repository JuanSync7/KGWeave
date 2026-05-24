"""v1.6-#3 G7 + v1.7-#3: PEP 634 ``match`` as PyMatchStatement w/ arm payload."""
from __future__ import annotations

from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "match_case.py"
FIXTURE_MIXED = FIXTURE_DIR / "match_arms_mixed.py"


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


def test_match_arms_payload_shape() -> None:
    """v1.7-#3: PyMatchStatement carries per-arm structural payload."""
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE_MIXED.read_bytes())
    matches = [n for n in nodes if n.kind == "PyMatchStatement"]
    assert len(matches) == 1, f"expected exactly 1 match, got {len(matches)}"
    m = matches[0]
    arms = m.payload.get("arms")
    assert isinstance(arms, list), f"payload missing 'arms' list, got {m.payload!r}"
    assert len(arms) == 7, f"expected 7 arms, got {len(arms)}: {arms!r}"

    # Each arm: pattern_kind, bound_names, has_guard
    for arm in arms:
        assert isinstance(arm, dict), f"arm not a dict: {arm!r}"
        assert "pattern_kind" in arm
        assert "bound_names" in arm and isinstance(arm["bound_names"], list)
        assert "has_guard" in arm and isinstance(arm["has_guard"], bool)

    kinds = [a["pattern_kind"] for a in arms]
    assert kinds == [
        "literal",
        "or",
        "sequence",
        "mapping",
        "class",
        "name",
        "wildcard",
    ], f"unexpected kinds order: {kinds}"

    # bound_names checks
    assert arms[0]["bound_names"] == []         # literal 1
    assert arms[1]["bound_names"] == []         # 'a' | 'b'
    assert sorted(arms[2]["bound_names"]) == ["x", "y"]
    assert arms[3]["bound_names"] == ["v"]
    assert sorted(arms[4]["bound_names"]) == ["px", "py"]
    assert arms[5]["bound_names"] == ["name"]
    assert arms[6]["bound_names"] == []

    # guards
    guards = [a["has_guard"] for a in arms]
    assert guards == [False, False, False, False, True, False, False]
