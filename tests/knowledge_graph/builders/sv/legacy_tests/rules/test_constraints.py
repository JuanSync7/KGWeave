"""S27: ConstraintDeclaration promotion.

The corpus's ``cls_corpus.sv`` declares constraints inside ``data_xact``:

* ``c_payload_nonzero``  — plain constraint block
* ``c_payload_range``    — plain constraint block (inside expression)
* ``c_static_demo``      — ``static`` constraint block
* ``c_external``         — ``extern`` constraint prototype (no body)

S27 promotes each ``ConstraintDeclarationSyntax`` and
``ConstraintPrototypeSyntax`` to ``role="constraint"`` with path
``<class_path>.<constraint_name>``, attaches a ``has_constraint`` edge from
the enclosing class, and stamps three boolean qualifier attributes
(``static`` / ``pure`` / ``extern``) detected structurally from the
TokenList of leading keywords. Constraint body expressions stay BLOB.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
CLS = HERE / "corpus" / "cls_corpus.sv"


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


def test_s27_constraint_nodes_promoted(cls_graph):
    """All four constraint declarations/prototypes are promoted with role=constraint
    and hierarchical paths ``cls_pkg.data_xact.<name>``."""
    cs = _by_role(cls_graph, "constraint")
    paths = sorted(c["semantic"]["path"] for c in cs)
    assert paths == [
        "cls_pkg.data_xact.c_external",
        "cls_pkg.data_xact.c_payload_nonzero",
        "cls_pkg.data_xact.c_payload_range",
        "cls_pkg.data_xact.c_static_demo",
    ], paths


def test_s27_has_constraint_edges(cls_graph):
    """Every constraint has exactly one inbound has_constraint edge from its
    enclosing class."""
    classes = {c["semantic"]["path"]: c for c in _by_role(cls_graph, "class")}
    cs = _by_role(cls_graph, "constraint")
    assert cs, "no constraint nodes promoted"
    for n in cs:
        parent_path = n["semantic"]["path"].rsplit(".", 1)[0]
        parent = classes[parent_path]
        edges = [e for e in cls_graph["edges"]
                 if e["type"] == "has_constraint"
                 and e["src"] == parent["id"]
                 and e["dst"] == n["id"]]
        assert len(edges) == 1, (
            f"{n['semantic']['path']}: expected 1 has_constraint edge, "
            f"got {len(edges)}"
        )


def test_s27_qualifier_attributes(cls_graph):
    """Static / pure / extern qualifiers detected structurally from the
    constraint's TokenList of qualifier keywords."""
    cs = {c["semantic"]["name"]: c for c in _by_role(cls_graph, "constraint")}

    plain = cs["c_payload_nonzero"]["semantic"]["attributes"]
    assert plain["static"] is False
    assert plain["pure"] is False
    assert plain["extern"] is False

    static_demo = cs["c_static_demo"]["semantic"]["attributes"]
    assert static_demo["static"] is True
    assert static_demo["pure"] is False
    assert static_demo["extern"] is False

    ext = cs["c_external"]["semantic"]["attributes"]
    assert ext["extern"] is True
    assert ext["static"] is False
    assert ext["pure"] is False


def test_s27_prototype_flag(cls_graph):
    """ConstraintPrototypeSyntax nodes carry ``prototype=True``; declarations
    with bodies carry ``prototype=False``."""
    cs = {c["semantic"]["name"]: c for c in _by_role(cls_graph, "constraint")}
    assert cs["c_external"]["semantic"]["attributes"]["prototype"] is True
    assert cs["c_payload_nonzero"]["semantic"]["attributes"]["prototype"] is False
    assert cs["c_static_demo"]["semantic"]["attributes"]["prototype"] is False


def test_s27_name_index_registers_constraint_paths(cls_graph):
    """Constraint paths are registered in the shared semantic_name_index so
    downstream rules can resolve them by qualified name."""
    idx = cls_graph.get("semantic_name_index", {})
    for nm in (
        "cls_pkg.data_xact.c_payload_nonzero",
        "cls_pkg.data_xact.c_payload_range",
        "cls_pkg.data_xact.c_static_demo",
        "cls_pkg.data_xact.c_external",
    ):
        assert nm in idx, f"missing name-index entry {nm!r}"


@pytest.fixture(scope="module")
def s52_graph():
    """Graph built from a minimal inline-randomize snippet — two inline
    constraint blocks inside module ``s52_top`` so path uniqueness can be
    checked."""
    text = (
        "class RC;\n"
        "  rand int a;\n"
        "  rand int b;\n"
        "endclass\n"
        "\n"
        "module s52_top;\n"
        "  initial begin\n"
        "    automatic RC obj = new;\n"
        "    int r;\n"
        "    r = obj.randomize() with { a < 5; };\n"
        "    r = obj.randomize() with { b > a; };\n"
        "  end\n"
        "endmodule\n"
    )
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s52_inline_constraint_block_nodes_promoted(s52_graph):
    """Both inline randomize() with { ... } blocks are promoted with
    role=inline_constraint_block under module s52_top."""
    nodes = [n for n in s52_graph["nodes"]
             if n.get("semantic", {}).get("role") == "inline_constraint_block"]
    assert len(nodes) == 2, (
        f"expected 2 inline_constraint_block nodes, got {len(nodes)}"
    )
    for n in nodes:
        path = n["semantic"]["path"]
        assert path.startswith("s52_top.__inline_constraint_"), (
            f"unexpected path prefix: {path!r}"
        )


def test_s52_paths_are_unique(s52_graph):
    """Each inline constraint block has a distinct path (byte-offset uniqueness)."""
    nodes = [n for n in s52_graph["nodes"]
             if n.get("semantic", {}).get("role") == "inline_constraint_block"]
    paths = [n["semantic"]["path"] for n in nodes]
    assert len(paths) == len(set(paths)), f"duplicate paths: {paths}"


def test_s52_has_inline_constraint_edges(s52_graph):
    """Each inline_constraint_block node has exactly one inbound
    has_inline_constraint edge from the enclosing module."""
    nodes = [n for n in s52_graph["nodes"]
             if n.get("semantic", {}).get("role") == "inline_constraint_block"]
    assert nodes, "no inline_constraint_block nodes found"
    module_nodes = {n["semantic"]["path"]: n for n in s52_graph["nodes"]
                    if n.get("semantic", {}).get("role") == "module"}
    mod = module_nodes.get("s52_top")
    assert mod is not None, "module s52_top not found in graph"
    for n in nodes:
        edges = [e for e in s52_graph["edges"]
                 if e["type"] == "has_inline_constraint"
                 and e["src"] == mod["id"]
                 and e["dst"] == n["id"]]
        assert len(edges) == 1, (
            f"{n['semantic']['path']}: expected 1 has_inline_constraint edge, "
            f"got {len(edges)}"
        )


def test_s52_declaration_body_stays_blob(s52_graph):
    """The ConstraintBlock that is the body of a named ConstraintDeclaration
    must NOT be promoted as inline_constraint_block — it stays BLOB."""
    # The s52_graph has class RC with no named constraints, so any promoted
    # inline_constraint_block nodes must all have synthetic names.
    nodes = [n for n in s52_graph["nodes"]
             if n.get("semantic", {}).get("role") == "inline_constraint_block"]
    for n in nodes:
        name = n["semantic"].get("name", "")
        assert name.startswith("__inline_constraint_"), (
            f"unexpected name for inline constraint block: {name!r}"
        )


def test_s52_declaration_body_not_promoted_in_cls_corpus(cls_graph):
    """In cls_corpus (which has named constraints), the ConstraintBlock body
    nodes (children of ConstraintDeclaration) are NOT promoted as
    inline_constraint_block.  Only the outer randomize-with blocks in
    s52_inline_top are inline nodes."""
    inline_nodes = [n for n in cls_graph["nodes"]
                    if n.get("semantic", {}).get("role") == "inline_constraint_block"]
    # The cls_corpus also includes s52_inline_top with 2 inline blocks.
    for n in inline_nodes:
        path = n["semantic"]["path"]
        assert "s52_inline_top" in path, (
            f"unexpected inline_constraint_block in named-constraint context: "
            f"{path!r}"
        )


def test_s27_pure_constraint_prototype():
    """``pure constraint c_pure;`` inside an interface-class-style class surfaces
    as ConstraintPrototypeSyntax with pure=True and prototype=True."""
    text = (
        "package pp;\n"
        "  virtual class abstract_xact;\n"
        "    pure constraint c_pure;\n"
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
    cs = _by_role(graph, "constraint")
    assert len(cs) == 1
    c = cs[0]
    assert c["semantic"]["path"] == "pp.abstract_xact.c_pure"
    attrs = c["semantic"]["attributes"]
    assert attrs["pure"] is True
    assert attrs["prototype"] is True
    assert attrs["static"] is False
