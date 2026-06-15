"""S38: GenvarDeclaration promotion.

``genvar_demo`` in ``corpus/fifo.sv`` exercises:

* ``genvar i;``      — single identifier
* ``genvar j, k;``   — two identifiers in one declaration

Expected behaviour per S38:
- One ``genvar`` node promoted per declared identifier.
- ``semantic["role"] == "genvar"``
- ``semantic["path"] == "<module>.<identifier>"``
- ``has_genvar`` edge from enclosing module to each genvar node.
- All three genvars (i, j, k) registered in the semantic_name_index.
- Byte-equal round-trip (enforced by ``test_roundtrip.py`` globally; the
  fixture below cross-checks via unlift so the test is self-contained).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
FIFO = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def genvar_graph():
    text = FIFO.read_text()
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


def _genvars(graph):
    return _by_role(graph, "genvar")


def _edges(graph, edge_type):
    return [e for e in graph["edges"] if e["type"] == edge_type]


# ---------------------------------------------------------------------------
# S38 — single-identifier genvar (genvar i;)
# ---------------------------------------------------------------------------

def test_s38_single_genvar_promoted(genvar_graph):
    """``genvar i`` from ``genvar i;`` is promoted as role=genvar."""
    matches = [g for g in _genvars(genvar_graph)
               if g["semantic"]["name"] == "i"
               and g["semantic"]["path"] == "genvar_demo.i"]
    assert len(matches) == 1, (
        f"expected exactly one genvar node for 'i', got {len(matches)}: "
        f"{[g['semantic'] for g in _genvars(genvar_graph)]}"
    )


def test_s38_single_genvar_path(genvar_graph):
    """Path key for single genvar follows <module>.<name> convention."""
    assert any(
        g["semantic"]["path"] == "genvar_demo.i"
        for g in _genvars(genvar_graph)
    ), "genvar_demo.i path not found"


# ---------------------------------------------------------------------------
# S38 — multi-identifier genvar (genvar j, k;)
# ---------------------------------------------------------------------------

def test_s38_multi_genvar_j_promoted(genvar_graph):
    """``genvar j`` from ``genvar j, k;`` is promoted as a separate node."""
    matches = [g for g in _genvars(genvar_graph)
               if g["semantic"]["name"] == "j"
               and g["semantic"]["path"] == "genvar_demo.j"]
    assert len(matches) == 1, (
        f"expected one genvar node for 'j', got {len(matches)}"
    )


def test_s38_multi_genvar_k_promoted(genvar_graph):
    """``genvar k`` from ``genvar j, k;`` is promoted as a separate node."""
    matches = [g for g in _genvars(genvar_graph)
               if g["semantic"]["name"] == "k"
               and g["semantic"]["path"] == "genvar_demo.k"]
    assert len(matches) == 1, (
        f"expected one genvar node for 'k', got {len(matches)}"
    )


def test_s38_total_genvars_in_module(genvar_graph):
    """Exactly three genvar nodes belong to genvar_demo (i, j, k)."""
    demo_genvars = [g for g in _genvars(genvar_graph)
                    if g["semantic"].get("path", "").startswith("genvar_demo.")]
    assert len(demo_genvars) == 3, (
        f"expected 3 genvar nodes for genvar_demo, got {len(demo_genvars)}: "
        f"{[g['semantic']['name'] for g in demo_genvars]}"
    )


# ---------------------------------------------------------------------------
# S38 — has_genvar edges from enclosing module
# ---------------------------------------------------------------------------

def test_s38_has_genvar_edges(genvar_graph):
    """Three has_genvar edges link genvar_demo → each genvar node."""
    ni = genvar_graph["semantic_name_index"]
    module_gid = ni.get("genvar_demo")
    assert module_gid is not None, "genvar_demo module not in name_index"

    hg_edges = [e for e in _edges(genvar_graph, "has_genvar")
                if e["src"] == module_gid]
    assert len(hg_edges) == 3, (
        f"expected 3 has_genvar edges from genvar_demo, got {len(hg_edges)}"
    )


def test_s38_name_index_registration(genvar_graph):
    """All three genvars are registered in semantic_name_index."""
    ni = genvar_graph["semantic_name_index"]
    for name in ("genvar_demo.i", "genvar_demo.j", "genvar_demo.k"):
        assert name in ni, f"{name} missing from semantic_name_index"


# ---------------------------------------------------------------------------
# S38 — byte-equal round-trip (losslessness)
# ---------------------------------------------------------------------------

def test_s38_roundtrip():
    """lift → emit reconstructs original fifo.sv text exactly (byte-equal)."""
    import pyslang as _pyslang
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.unlift import emit

    text = FIFO.read_text()
    tree = _pyslang.SyntaxTree.fromText(text)
    graph = lift(tree)
    emitted = emit(graph)
    assert emitted == text, (
        f"round-trip mismatch: {len(text)} original chars vs "
        f"{len(emitted)} emitted chars"
    )
