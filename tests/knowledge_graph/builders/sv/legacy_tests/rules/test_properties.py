"""S14: PropertyDeclaration promotion.

The corpus's ``fifo_asserts.sv`` declares one ``property
p_push_implies_not_full`` inside ``module fifo_asserts``. S14 promotes the
``PropertyDeclarationSyntax`` graph node to ``role="property"`` with path
``fifo_asserts.p_push_implies_not_full`` and emits a
``fifo_asserts --has_property--> property`` edge analogous to S10's
``has_function``.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
BIND = HERE / "corpus" / "fifo_asserts.sv"


@pytest.fixture(scope="module")
def bind_graph():
    text = BIND.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _by_role(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role]


def test_s14_property_node_promoted(bind_graph):
    """The property declaration is promoted with role=property, correct name,
    and hierarchical path ``<module>.<property_name>``."""
    props = _by_role(bind_graph, "property")
    # S77 added two parameterised properties (``p_with_ports``,
    # ``p_dir_ports``) to the same corpus module, so this scope now
    # carries three promoted properties.
    assert len(props) == 3, f"expected three promoted properties, got {len(props)}"
    names = {p["semantic"]["name"] for p in props}
    paths = {p["semantic"]["path"] for p in props}
    assert "p_push_implies_not_full" in names
    assert "fifo_asserts.p_push_implies_not_full" in paths
    assert "p_with_ports" in names
    assert "fifo_asserts.p_with_ports" in paths
    assert "p_dir_ports" in names
    assert "fifo_asserts.p_dir_ports" in paths


def test_s14_has_property_edge(bind_graph):
    """The parent module emits exactly one has_property edge to the
    promoted property node."""
    props = _by_role(bind_graph, "property")
    assert props
    prop_id = next(p["id"] for p in props
                   if p["semantic"]["name"] == "p_push_implies_not_full")
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules if m["semantic"]["name"] == "fifo_asserts"), None)
    assert parent is not None, "fifo_asserts module not promoted"
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_property"
             and e["src"] == parent["id"]
             and e["dst"] == prop_id]
    assert len(edges) == 1, f"expected exactly one has_property edge, got {len(edges)}"


def test_s14_name_index_registers_path(bind_graph):
    """The hierarchical path is registered in semantic_name_index so downstream
    rules can resolve the property by qualified name."""
    idx = bind_graph.get("semantic_name_index", {})
    assert "fifo_asserts.p_push_implies_not_full" in idx


# ---------------------------------------------------------------------------
# S15 — SequenceDeclaration
# ---------------------------------------------------------------------------


def test_s15_sequence_node_promoted(bind_graph):
    """The sequence declaration is promoted with role=sequence, correct name,
    and hierarchical path ``<module>.<sequence_name>``."""
    seqs = _by_role(bind_graph, "sequence")
    # S77 added a parameterised ``s_with_ports`` to the same corpus module.
    assert len(seqs) == 2, f"expected two promoted sequences, got {len(seqs)}"
    names = {s["semantic"]["name"] for s in seqs}
    paths = {s["semantic"]["path"] for s in seqs}
    assert "s_push_then_full" in names
    assert "fifo_asserts.s_push_then_full" in paths
    assert "s_with_ports" in names
    assert "fifo_asserts.s_with_ports" in paths


def test_s15_has_sequence_edge(bind_graph):
    """The parent module emits exactly one has_sequence edge to the promoted
    sequence node."""
    seqs = _by_role(bind_graph, "sequence")
    assert seqs
    seq_id = next(s["id"] for s in seqs
                  if s["semantic"]["name"] == "s_push_then_full")
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules if m["semantic"]["name"] == "fifo_asserts"), None)
    assert parent is not None, "fifo_asserts module not promoted"
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_sequence"
             and e["src"] == parent["id"]
             and e["dst"] == seq_id]
    assert len(edges) == 1, f"expected exactly one has_sequence edge, got {len(edges)}"


def test_s15_name_index_registers_path(bind_graph):
    """The hierarchical path is registered in semantic_name_index so downstream
    rules can resolve the sequence by qualified name."""
    idx = bind_graph.get("semantic_name_index", {})
    assert "fifo_asserts.s_push_then_full" in idx
