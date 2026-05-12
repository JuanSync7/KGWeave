"""TDD anchor for the generic multi-file ``build_kg`` entry point.

The previous multi-module path concatenated SV strings into a single
``SyntaxTree`` to fake multi-file. The real production path is two
independent ``SyntaxTree``s added to the same ``Compilation``. This test
asserts that ``build_kg([FIFO, TOP])`` produces ONE queryable graph with
cross-tree edges intact, in particular ``top.u_fifo --of_module--> fifo``.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FIFO = HERE / "fifo.sv"
TOP = HERE / "top.sv"


def test_build_kg_unifies_cross_file_of_module_edge():
    """build_kg([FIFO, TOP]) must materialise the top.u_fifo --of_module--> fifo edge."""
    from research.ast_experiment.src.build import build_kg
    from scripts.semantic import find_by_name, neighbors

    graph, _trees, _comp = build_kg([FIFO, TOP])

    inst = find_by_name(graph, "top.u_fifo")
    assert inst is not None and inst["semantic"]["role"] == "instance"
    of_mod = neighbors(graph, inst["id"], edge_type="of_module", direction="out")
    assert len(of_mod) == 1, (
        f"expected exactly one of_module edge from top.u_fifo, got {len(of_mod)}"
    )
    assert of_mod[0]["semantic"]["name"] == "fifo"


def test_build_kg_node_ids_globally_unique():
    """No two nodes in the combined graph share an id (lift counter collision check)."""
    from research.ast_experiment.src.build import build_kg

    graph, _trees, _comp = build_kg([FIFO, TOP])
    ids = [n["id"] for n in graph["nodes"]]
    assert len(ids) == len(set(ids)), "duplicate node ids in combined graph"


def test_build_kg_both_modules_promoted():
    """Both 'fifo' and 'top' modules are promoted under the same name_index."""
    from research.ast_experiment.src.build import build_kg
    from scripts.semantic import find_by_name

    graph, _trees, _comp = build_kg([FIFO, TOP])
    assert find_by_name(graph, "fifo")["semantic"]["role"] == "module"
    assert find_by_name(graph, "top")["semantic"]["role"] == "module"
