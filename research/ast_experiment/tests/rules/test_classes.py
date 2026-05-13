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
        "cls_pkg.printable_xact",
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
    assert len(edges) == 5, f"expected 5 has_class edges, got {len(edges)}"


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


def _edges(graph, etype):
    return [e for e in graph["edges"] if e["type"] == etype]


def test_s25_extends_edge_data_xact(cls_graph):
    """``data_xact extends base_xact`` emits a single ``extends`` edge from
    the data_xact class node to the resolved base_xact class node."""
    classes = {c["semantic"]["name"]: c for c in _by_role(cls_graph, "class")}
    base = classes["base_xact"]
    data = classes["data_xact"]
    matches = [e for e in _edges(cls_graph, "extends")
               if e["src"] == data["id"] and e["dst"] == base["id"]]
    assert len(matches) == 1, f"expected one extends edge, got {matches}"
    assert matches[0]["payload"].get("unresolved") is not True


def test_s25_extends_edge_printable_xact(cls_graph):
    """``printable_xact extends base_xact`` resolves the same parent."""
    classes = {c["semantic"]["name"]: c for c in _by_role(cls_graph, "class")}
    base = classes["base_xact"]
    pr = classes["printable_xact"]
    matches = [e for e in _edges(cls_graph, "extends")
               if e["src"] == pr["id"] and e["dst"] == base["id"]]
    assert len(matches) == 1


def test_s25_implements_edge_printable_xact(cls_graph):
    """``printable_xact implements printable`` emits a single
    ``implements`` edge to the interface-class node."""
    classes = {c["semantic"]["name"]: c for c in _by_role(cls_graph, "class")}
    iface = classes["printable"]
    pr = classes["printable_xact"]
    matches = [e for e in _edges(cls_graph, "implements")
               if e["src"] == pr["id"] and e["dst"] == iface["id"]]
    assert len(matches) == 1


def test_s25_extends_name_attribute(cls_graph):
    """The ClassDeclaration attributes include the parent class name string
    when an ExtendsClause is present, and OMIT it otherwise."""
    classes = {c["semantic"]["name"]: c for c in _by_role(cls_graph, "class")}
    assert classes["data_xact"]["semantic"]["attributes"]["extends_name"] == "base_xact"
    assert classes["printable_xact"]["semantic"]["attributes"]["extends_name"] == "base_xact"
    # No ExtendsClause on these — attribute must not be present.
    assert "extends_name" not in classes["base_xact"]["semantic"]["attributes"]
    assert "extends_name" not in classes["para_xact"]["semantic"]["attributes"]


def test_s25_implements_names_attribute(cls_graph):
    """The ClassDeclaration attributes include the ordered list of
    implemented interface-class names when an ImplementsClause is present."""
    classes = {c["semantic"]["name"]: c for c in _by_role(cls_graph, "class")}
    assert classes["printable_xact"]["semantic"]["attributes"]["implements_names"] == ["printable"]
    assert "implements_names" not in classes["data_xact"]["semantic"]["attributes"]


def test_s25_multiple_implements():
    """Multiple comma-separated interfaces in ``implements`` emit one edge
    each in source order, with all targets resolved."""
    text = (
        "package multi_pkg;\n"
        "  interface class ifa;\n"
        "  endclass\n"
        "  interface class ifb;\n"
        "  endclass\n"
        "  class hub implements ifa, ifb;\n"
        "  endclass\n"
        "endpackage\n"
    )
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    classes = {c["semantic"]["name"]: c for c in _by_role(graph, "class")}
    hub = classes["hub"]
    assert hub["semantic"]["attributes"]["implements_names"] == ["ifa", "ifb"]
    imp = [e for e in graph["edges"]
           if e["type"] == "implements" and e["src"] == hub["id"]]
    assert len(imp) == 2
    dsts = [e["dst"] for e in imp]
    assert dsts == [classes["ifa"]["id"], classes["ifb"]["id"]]
    assert all(e["payload"].get("unresolved") is not True for e in imp)


def test_s25_unresolved_extends_target():
    """An ``extends`` clause whose parent isn't declared anywhere still
    emits an edge — with ``unresolved=True`` payload and a synthetic
    placeholder destination so downstream queries can still see it."""
    text = (
        "package fwd_pkg;\n"
        "  class orphan extends unknown_base;\n"
        "  endclass\n"
        "endpackage\n"
    )
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    classes = {c["semantic"]["name"]: c for c in _by_role(graph, "class")}
    orphan = classes["orphan"]
    matches = [e for e in graph["edges"]
               if e["type"] == "extends" and e["src"] == orphan["id"]]
    assert len(matches) == 1
    e = matches[0]
    assert e["payload"].get("unresolved") is True
    assert e["dst"] == "_unresolved.unknown_base"
    assert orphan["semantic"]["attributes"]["extends_name"] == "unknown_base"


def test_s24_name_index_registers_paths(cls_graph):
    """All four class hierarchical paths are registered in the shared
    semantic_name_index so downstream rules (S25/S26) can resolve them by
    qualified name."""
    idx = cls_graph.get("semantic_name_index", {})
    for nm in ("cls_pkg.base_xact", "cls_pkg.data_xact",
               "cls_pkg.printable", "cls_pkg.para_xact",
               "cls_pkg.printable_xact"):
        assert nm in idx, f"missing name-index entry {nm!r}"
