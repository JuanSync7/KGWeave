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
FIXTURE_NESTED = FIXTURE_DIR / "comprehensions_nested.py"


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


def test_walker_parents_comprehensions_to_nearest_lexical_scope() -> None:
    """v1.7-#2: PyComprehension.parent_idx must point at the nearest
    enclosing function / class / comprehension, not unconditionally
    at PyModule."""
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE_NESTED.read_bytes())

    def _kind_of(idx: int | None) -> str:
        assert idx is not None
        return nodes[idx].kind

    def _name_of(idx: int | None) -> str:
        assert idx is not None
        return nodes[idx].name

    comps = [(i, n) for i, n in enumerate(nodes) if n.kind == "PyComprehension"]
    # Fixture has 5 comprehensions total: TOP, foo, outer-outer,
    # outer-inner, Widget.method.
    assert len(comps) == 5, [
        (n.start, n.end, n.payload) for _, n in comps
    ]

    # Sort by start so we can address them positionally in source order.
    comps.sort(key=lambda pair: pair[1].start)
    top_idx, top = comps[0]
    foo_idx, foo_comp = comps[1]
    outer_outer_idx, outer_outer = comps[2]
    outer_inner_idx, outer_inner = comps[3]
    method_idx, method_comp = comps[4]

    # Case 1: module-level stays parented to PyModule.
    assert _kind_of(top.parent_idx) == "PyModule"

    # Case 2: comp inside def foo -> parent is PyFunction "foo".
    assert _kind_of(foo_comp.parent_idx) == "PyFunction"
    assert _name_of(foo_comp.parent_idx) == "foo"

    # Case 3a: outer comp parent is PyFunction "outer".
    assert _kind_of(outer_outer.parent_idx) == "PyFunction"
    assert _name_of(outer_outer.parent_idx) == "outer"
    # Case 3b: inner comp parent is the outer PyComprehension.
    assert outer_inner.parent_idx == outer_outer_idx, (
        f"inner.parent_idx={outer_inner.parent_idx}, "
        f"outer_outer_idx={outer_outer_idx}"
    )

    # Case 4: method-body comp parent is PyFunction "method", NOT
    # the enclosing PyClass.
    assert _kind_of(method_comp.parent_idx) == "PyFunction"
    assert _name_of(method_comp.parent_idx) == "method"
