"""S19: ProceduralAssign / ProceduralDeassign promotion.

The corpus's ``fifo_asserts.sv`` includes ``module proc_assign_demo`` with an
always block that contains both a ``assign r = din;`` (procedural
continuous assign) and a ``deassign r;`` statement. S19 promotes each
``ProceduralAssignStatementSyntax`` and ``ProceduralDeassignStatementSyntax``
node to ``role="procedural_assign"`` / ``role="procedural_deassign"`` under
the enclosing module (NOT the always block), attaches a
``has_procedural_assign`` edge from the parent module, stamps
``attributes["lhs"]`` with the structurally extracted target identifier,
and — when the LHS resolves via the shared name index — emits a
``drives`` edge to the target net.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
BIND = HERE / "fifo_asserts.sv"


@pytest.fixture(scope="module")
def bind_graph():
    text = BIND.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _by_role(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role]


def test_s19_procedural_assign_promoted(bind_graph):
    """The ``assign r = din;`` statement is promoted with role
    procedural_assign and a path under the parent module."""
    pas = _by_role(bind_graph, "procedural_assign")
    assert len(pas) == 1, f"expected 1 procedural_assign, got {len(pas)}"
    node = pas[0]
    assert node["semantic"]["path"].startswith("proc_assign_demo.")
    assert node["semantic"]["attributes"]["lhs"] == "r"


def test_s19_procedural_deassign_promoted(bind_graph):
    """The ``deassign r;`` statement is promoted with role
    procedural_deassign and the same LHS."""
    pds = _by_role(bind_graph, "procedural_deassign")
    assert len(pds) == 1, f"expected 1 procedural_deassign, got {len(pds)}"
    node = pds[0]
    assert node["semantic"]["path"].startswith("proc_assign_demo.")
    assert node["semantic"]["attributes"]["lhs"] == "r"


def test_s19_parent_is_module_not_always_block(bind_graph):
    """The has_procedural_assign edge runs from the enclosing module
    (proc_assign_demo) — never from the AlwaysBlock or SequentialBlock."""
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules
                   if m["semantic"]["name"] == "proc_assign_demo"), None)
    assert parent is not None, "proc_assign_demo module not promoted"
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_procedural_assign"
             and e["src"] == parent["id"]]
    assert len(edges) == 2, (
        f"expected 2 has_procedural_assign edges from proc_assign_demo, "
        f"got {len(edges)}"
    )


def test_s19_name_index_registers_paths(bind_graph):
    """Both synthesized paths are registered in semantic_name_index so
    downstream rules can resolve procedural assigns by qualified name."""
    idx = bind_graph.get("semantic_name_index", {})
    pas = _by_role(bind_graph, "procedural_assign")
    pds = _by_role(bind_graph, "procedural_deassign")
    for n in pas + pds:
        path = n["semantic"]["path"]
        assert path in idx, f"name_index missing {path}"


def test_s19_drives_edge_resolves_to_net(bind_graph):
    """The procedural-assign LHS ``r`` resolves to the local net
    ``proc_assign_demo.r`` via the shared name index, so a drives edge
    is emitted from the procedural_assign node to the net."""
    pas = _by_role(bind_graph, "procedural_assign")
    assert pas, "no procedural_assign node"
    pa = pas[0]
    nets = [n for n in _by_role(bind_graph, "net")
            if n["semantic"]["path"] == "proc_assign_demo.r"]
    assert nets, "proc_assign_demo.r net not promoted"
    net_id = nets[0]["id"]
    drives = [e for e in bind_graph["edges"]
              if e["type"] == "drives"
              and e["src"] == pa["id"]
              and e["dst"] == net_id]
    assert len(drives) == 1, (
        f"expected one drives edge procedural_assign→r, got {len(drives)}"
    )
