"""v1.7-#5: PyLambda kind with scope-aware parent and capture set.

Walker emits one PyLambda per ``lambda`` expression. ``parent_idx``
points at the nearest enclosing scope (PyModule / PyFunction / PyClass /
outer PyLambda or PyComprehension). ``payload["captures"]`` lists names
referenced inside the body that are NOT parameters of the lambda
itself; verification against actual lexical bindings is deferred to a
later slate.
"""
from __future__ import annotations

from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "lambdas_capture.py"


def _lambdas_in_source_order():
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    lambdas = [(i, n) for i, n in enumerate(nodes) if n.kind == "PyLambda"]
    lambdas.sort(key=lambda pair: pair[1].start)
    return nodes, lambdas


def test_walker_emits_one_pylambda_per_lambda() -> None:
    _, lambdas = _lambdas_in_source_order()
    assert len(lambdas) == 7, [
        (n.start, n.payload) for _, n in lambdas
    ]


def test_walker_records_captures_excluding_params() -> None:
    _, lambdas = _lambdas_in_source_order()
    expected_captures = [
        set(),         # 1. lambda: 0
        set(),         # 2. lambda x: x + 1
        {"y"},         # 3. inside f(), captures y
        {"foo"},       # 4. lambda x: foo(x) at module level
        {"self"},      # 5. method lambda capturing self
        set(),         # 6. outer of nested
        {"x"},         # 7. inner of nested captures x
    ]
    got = [set(n.payload.get("captures", [])) for _, n in lambdas]
    assert got == expected_captures, got


def test_walker_parents_lambdas_to_nearest_enclosing_scope() -> None:
    nodes, lambdas = _lambdas_in_source_order()

    def kind_of(idx):
        assert idx is not None
        return nodes[idx].kind

    def name_of(idx):
        assert idx is not None
        return nodes[idx].name

    # 1. top-level no-cap
    assert kind_of(lambdas[0][1].parent_idx) == "PyModule"
    # 2. add_one at module level
    assert kind_of(lambdas[1][1].parent_idx) == "PyModule"
    # 3. inside f -> PyFunction f
    assert kind_of(lambdas[2][1].parent_idx) == "PyFunction"
    assert name_of(lambdas[2][1].parent_idx) == "f"
    # 4. call_foo at module level
    assert kind_of(lambdas[3][1].parent_idx) == "PyModule"
    # 5. method lambda -> PyFunction m
    assert kind_of(lambdas[4][1].parent_idx) == "PyFunction"
    assert name_of(lambdas[4][1].parent_idx) == "m"
    # 6. outer nested -> PyModule
    assert kind_of(lambdas[5][1].parent_idx) == "PyModule"
    # 7. inner nested -> outer PyLambda
    outer_idx = lambdas[5][0]
    assert lambdas[6][1].parent_idx == outer_idx, (
        f"inner.parent_idx={lambdas[6][1].parent_idx} outer_idx={outer_idx}"
    )
