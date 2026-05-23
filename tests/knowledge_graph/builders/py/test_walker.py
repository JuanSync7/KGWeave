"""Walker tests — libcst-driven Python lift.

The Python walker emits a flat list of :class:`PyNode` objects covering
the v1 set: module / function / class / import. Each node carries a
byte-precise span and a parent index (the document is index 0).
"""

from __future__ import annotations

from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


def _kinds(nodes) -> list[str]:
    return [n.kind for n in nodes]


def test_walker_emits_module_function_class_import_for_simple_module() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    content = (FIXTURE_DIR / "simple_module.py").read_bytes()
    nodes = lift_python(content)

    kinds = _kinds(nodes)
    # Required v1 kinds at minimum:
    assert "PyModule" in kinds
    assert "PyImport" in kinds
    assert "PyFunction" in kinds
    assert "PyClass" in kinds
    # Methods live INSIDE the class -> represented as PyFunction children.
    # ``Counter.__init__`` and ``Counter.bump`` are functions, so the
    # walker must report >= 3 PyFunction nodes (add, __init__, bump).
    n_funcs = sum(1 for n in nodes if n.kind == "PyFunction")
    assert n_funcs >= 3, f"expected >=3 PyFunction, got {n_funcs}: {kinds}"
    n_classes = sum(1 for n in nodes if n.kind == "PyClass")
    assert n_classes == 1


def test_walker_module_node_is_root_and_first() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    content = (FIXTURE_DIR / "simple_module.py").read_bytes()
    nodes = lift_python(content)
    assert nodes, "walker returned no nodes"
    assert nodes[0].kind == "PyModule"
    assert nodes[0].parent_idx is None
    # All other nodes have a parent in the list.
    for n in nodes[1:]:
        assert n.parent_idx is not None
        assert 0 <= n.parent_idx < len(nodes)


def test_walker_function_node_carries_name() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    content = (FIXTURE_DIR / "simple_module.py").read_bytes()
    nodes = lift_python(content)
    fn_names = {n.name for n in nodes if n.kind == "PyFunction"}
    assert "add" in fn_names
    assert "bump" in fn_names


def test_walker_import_records_module_name() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    content = (FIXTURE_DIR / "simple_module.py").read_bytes()
    nodes = lift_python(content)
    imports = [n for n in nodes if n.kind == "PyImport"]
    assert imports, "expected at least one PyImport"
    # The fixture has ``import math`` — its lifted name is ``math``.
    assert any(n.name == "math" for n in imports)


def test_walker_from_import_records_imported_symbols() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    content = (FIXTURE_DIR / "multi_file_b.py").read_bytes()
    nodes = lift_python(content)
    # ``from multi_file_a import Widget, make_widget`` should emit at
    # least one PyImport whose payload references multi_file_a, and the
    # imported symbol names should appear in payload['names'].
    imports = [n for n in nodes if n.kind == "PyImport"]
    assert imports
    names_seen: set[str] = set()
    for n in imports:
        names_seen.update(n.payload.get("names", []))
    assert {"Widget", "make_widget"}.issubset(names_seen)


def test_walker_spans_are_within_content_bounds() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    content = (FIXTURE_DIR / "simple_module.py").read_bytes()
    nodes = lift_python(content)
    n_bytes = len(content)
    for n in nodes:
        assert 0 <= n.start <= n.end <= n_bytes
