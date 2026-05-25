"""v1.9-#1: PyComprehension.captures free-name list.

The walker emits a ``captures: list[str]`` field on every
PyComprehension payload, listing free names referenced inside the
comprehension body that are NOT bound by the comprehension's own
iter-target(s), walrus-assigned locals, or nested comprehension
locals.

This mirrors the PyLambda.captures contract established in v1.7-#5.
The walker stays a pure structural lifter — classification of those
names against enclosing lexical scopes is the connector's job
(v1.9-#1 wires that up by parametrising the v1.8-#3 indexer over
PyComprehension as well).
"""
from __future__ import annotations

from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "comprehension_captures.py"


def test_walker_records_captures_on_pycomprehension() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    comps = [n for n in nodes if n.kind == "PyComprehension"]
    assert len(comps) == 1, [n.payload for n in comps]
    captures = comps[0].payload.get("captures")
    assert isinstance(captures, list), captures
    # ``x`` is the iter-target -> must NOT appear.
    # Everything else loaded in the body is free w.r.t. the comp scope:
    #   y, OFFSET, len, str, mystery, range
    assert "x" not in captures, captures
    assert set(captures) == {
        "y",
        "OFFSET",
        "len",
        "str",
        "mystery",
        "range",
    }, captures
    # Must be sorted, like PyLambda.captures.
    assert captures == sorted(captures), captures
