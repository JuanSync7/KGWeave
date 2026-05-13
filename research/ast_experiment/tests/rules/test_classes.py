"""S24: ClassDeclaration promotion.

The corpus's ``cls_corpus.sv`` declares ``package cls_pkg`` containing four
classes that span the structural-modifier matrix:

* ``base_xact``  — ``virtual class``
* ``data_xact``  — plain class with ``extends base_xact``
* ``printable``  — ``interface class``
* ``para_xact``  — parameterized class with ``#(type T = int)``

S24 promotes each ``ClassDeclarationSyntax`` graph node to ``role="class"``
with path ``<owner>.<class_name>``, attaches a ``has_class`` edge from the
parent module / package / interface, and stamps four boolean modifier
attributes (``virtual`` / ``interface_class`` / ``final`` / ``parameterized``)
detected structurally from direct-child Tokens and SyntaxNodes.

Class members (properties, methods, extends/implements clauses) remain BLOB
at this S-rule and will be promoted by S25 and S26 — both will use the
``class_stack`` already maintained by pass 1 of ``dispatch.promote``.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
CLS = HERE / "cls_corpus.sv"


@pytest.fixture(scope="module")
def cls_graph():
    text = CLS.read_text()
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


def test_s24_class_nodes_promoted(cls_graph):
    """All four class declarations are promoted with role=class and
    hierarchical paths ``cls_pkg.<class_name>``."""
    classes = _by_role(cls_graph, "class")
    paths = sorted(c["semantic"]["path"] for c in classes)
    assert paths == [
        "cls_pkg.base_xact",
        "cls_pkg.data_xact",
        "cls_pkg.para_xact",
        "cls_pkg.printable",
    ], paths


def test_s24_has_class_edges(cls_graph):
    """The parent package emits one has_class edge per promoted class."""
    classes = _by_role(cls_graph, "class")
    packages = _by_role(cls_graph, "package")
    pkg = next((p for p in packages if p["semantic"]["name"] == "cls_pkg"), None)
    assert pkg is not None, "cls_pkg package not promoted"
    cls_ids = {c["id"] for c in classes}
    edges = [e for e in cls_graph["edges"]
             if e["type"] == "has_class"
             and e["src"] == pkg["id"]
             and e["dst"] in cls_ids]
    assert len(edges) == 4, f"expected 4 has_class edges, got {len(edges)}"


def test_s24_modifier_attributes(cls_graph):
    """Structural-modifier attributes are detected correctly for each class."""
    classes = {c["semantic"]["name"]: c for c in _by_role(cls_graph, "class")}

    base = classes["base_xact"]["semantic"]["attributes"]
    assert base["virtual"] is True
    assert base["interface_class"] is False
    assert base["parameterized"] is False
    assert base["final"] is False

    data = classes["data_xact"]["semantic"]["attributes"]
    assert data["virtual"] is False
    assert data["interface_class"] is False
    assert data["parameterized"] is False

    pr = classes["printable"]["semantic"]["attributes"]
    assert pr["interface_class"] is True
    assert pr["virtual"] is False

    para = classes["para_xact"]["semantic"]["attributes"]
    assert para["parameterized"] is True
    assert para["virtual"] is False
    assert para["interface_class"] is False


def test_s24_name_index_registers_paths(cls_graph):
    """All four class hierarchical paths are registered in the shared
    semantic_name_index so downstream rules (S25/S26) can resolve them by
    qualified name."""
    idx = cls_graph.get("semantic_name_index", {})
    for nm in ("cls_pkg.base_xact", "cls_pkg.data_xact",
               "cls_pkg.printable", "cls_pkg.para_xact"):
        assert nm in idx, f"missing name-index entry {nm!r}"
