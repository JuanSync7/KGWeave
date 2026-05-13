"""S29: Extern module/interface/program declaration promotion.

The corpus ``extern_corpus.sv`` declares three extern headers — one each of
``extern module``, ``extern interface``, ``extern program`` — followed by
the full bodies of the same three constructs. S29 promotes:

* The three ExternModuleDeclSyntax nodes → role=extern_decl with
  attributes["kind"] ∈ {"module", "interface", "program"}. All three live
  at compilation-unit scope (root-anchored, no enclosing parent).
* The ``declares`` edge from each extern decl to the matching full
  declaration via the shared semantic name index (S1 registers the full
  module / interface under the bare name).
* The ports attribute carries the port-name list from the header.

The full module / interface / program declarations are promoted by S1
(modules / interfaces / packages); the program body itself is promoted
by S30, which is intentionally out of scope here — S29 only owns the
extern headers.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
EXT = HERE / "extern_corpus.sv"


@pytest.fixture(scope="module")
def ext_graph():
    text = EXT.read_text()
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


def test_s29_extern_decls_promoted(ext_graph):
    """All three extern decls (module / interface / program) appear as
    role=extern_decl nodes at compilation-unit scope."""
    externs = _by_role(ext_graph, "extern_decl")
    assert len(externs) == 3
    by_name = {n["semantic"]["name"]: n for n in externs}
    assert set(by_name) == {"ext_mod", "ext_if", "ext_prog"}
    # cu-scope: path equals the bare declared name.
    for name, node in by_name.items():
        assert node["semantic"]["path"] == name


def test_s29_extern_kind_attribute(ext_graph):
    """The ``kind`` attribute discriminates the three header variants."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    assert externs["ext_mod"]["semantic"]["attributes"]["kind"] == "module"
    assert externs["ext_if"]["semantic"]["attributes"]["kind"] == "interface"
    assert externs["ext_prog"]["semantic"]["attributes"]["kind"] == "program"


def test_s29_extern_port_list(ext_graph):
    """The port-name list is extracted structurally from the header."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    # extern module ext_mod (... clk, q)
    assert externs["ext_mod"]["semantic"]["attributes"]["ports"] == ["clk", "q"]
    # extern interface ext_if (... clk)
    assert externs["ext_if"]["semantic"]["attributes"]["ports"] == ["clk"]
    # extern program ext_prog ()
    assert externs["ext_prog"]["semantic"]["attributes"]["ports"] == []


def test_s29_declares_edge_resolves_module(ext_graph):
    """The ``ext_mod`` extern decl has a ``declares`` edge pointing to the
    full module declaration resolved via the shared name index."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    modules = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "module")}
    assert "ext_mod" in modules, "full module ext_mod must be promoted by S1"
    ext_id = externs["ext_mod"]["id"]
    mod_id = modules["ext_mod"]["id"]
    edges = [e for e in ext_graph["edges"]
             if e["type"] == "declares"
             and e["src"] == ext_id
             and e["dst"] == mod_id]
    assert len(edges) == 1, f"expected 1 declares edge, got {len(edges)}"


def test_s29_declares_edge_resolves_interface(ext_graph):
    """The ``ext_if`` extern decl has a ``declares`` edge to the full
    interface declaration."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    interfaces = {n["semantic"]["name"]: n
                  for n in _by_role(ext_graph, "interface")}
    assert "ext_if" in interfaces, "full interface ext_if must be promoted by S1"
    ext_id = externs["ext_if"]["id"]
    if_id = interfaces["ext_if"]["id"]
    edges = [e for e in ext_graph["edges"]
             if e["type"] == "declares"
             and e["src"] == ext_id
             and e["dst"] == if_id]
    assert len(edges) == 1


def test_s29_no_has_extern_decl_at_cu_scope(ext_graph):
    """At compilation-unit scope the extern decls are root-anchored — no
    ``has_extern_decl`` containment edge should be emitted."""
    edges = [e for e in ext_graph["edges"] if e["type"] == "has_extern_decl"]
    assert edges == [], (
        f"cu-scope extern decls must not emit has_extern_decl; got {edges}"
    )
