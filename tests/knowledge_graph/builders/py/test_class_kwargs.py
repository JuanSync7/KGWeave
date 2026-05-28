"""v1.15-#3: lift all class-definition keyword arguments onto PyClass.

Walker must populate ``payload['class_kwargs']: dict[str, str]`` with every
class-definition keyword whose value flattens to a dotted name. Non-name
values (string literals, calls) are skipped. ``metaclass`` is preserved in
its own ``payload['metaclass']`` slot AND mirrored into ``class_kwargs``.
Empty dict (``{}``) is recorded when no kwargs are present.
"""
from __future__ import annotations

from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


def test_walker_records_class_kwargs_dotted_names() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python((FIXTURE_DIR / "class_kwargs.py").read_bytes())
    by_name = {n.name: n for n in nodes if n.kind == "PyClass"}
    assert by_name["Child"].payload["class_kwargs"] == {
        "name": "ALPHA",
        "config": "BETA",
    }


def test_walker_class_kwargs_includes_metaclass() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python((FIXTURE_DIR / "class_kwargs.py").read_bytes())
    by_name = {n.name: n for n in nodes if n.kind == "PyClass"}
    other = by_name["Other"]
    assert other.payload["class_kwargs"] == {"metaclass": "MetaCls"}
    # v1.8-#4 slot must be preserved.
    assert other.payload["metaclass"] == "MetaCls"


def test_walker_class_kwargs_empty_dict_when_no_kwargs() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python((FIXTURE_DIR / "class_kwargs.py").read_bytes())
    by_name = {n.name: n for n in nodes if n.kind == "PyClass"}
    assert by_name["Bare"].payload["class_kwargs"] == {}
    assert by_name["Base"].payload["class_kwargs"] == {}
