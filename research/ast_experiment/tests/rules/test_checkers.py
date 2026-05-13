"""S28: CheckerDeclaration + CheckerInstantiation promotion.

The corpus ``checker_corpus.sv`` declares one checker ``c_mutex`` (at
compilation-unit scope) and one module ``checker_corpus_top`` that
instantiates it as ``u_mutex``. S28 promotes:

* The CheckerDeclarationSyntax → role=checker, path ``c_mutex``,
  ``has_checker`` skipped (no enclosing module — compilation-unit scope).
* The internal PropertyDeclaration ``p_mutex`` → role=property, path
  ``c_mutex.p_mutex`` (attached via the checker_stack /
  module_stack push that the S28 branch performs).
* The internal ConcurrentAssertionStatement ``a_mutex`` → role=assertion,
  path ``c_mutex.a_mutex``.
* The internal ClockingDeclaration → role=clocking, path
  ``c_mutex.<name>``.
* The module-body HierarchyInstantiationSyntax that names ``c_mutex`` →
  role=checker_instance (re-classified by rule_s6 against the
  ``checker:<name>`` name-index entry), path
  ``checker_corpus_top.u_mutex``, ``has_checker_instance`` edge from
  the module, ``of_checker`` edge to the checker declaration.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
CHK = HERE / "checker_corpus.sv"


@pytest.fixture(scope="module")
def chk_graph():
    text = CHK.read_text()
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


def test_s28_checker_declaration_promoted(chk_graph):
    """c_mutex is promoted with role=checker at compilation-unit scope."""
    checkers = _by_role(chk_graph, "checker")
    assert len(checkers) == 1
    c = checkers[0]
    assert c["semantic"]["name"] == "c_mutex"
    assert c["semantic"]["path"] == "c_mutex"


def test_s28_checker_instance_promoted(chk_graph):
    """u_mutex is promoted as role=checker_instance under
    checker_corpus_top, with the checker name stamped in attributes."""
    instances = _by_role(chk_graph, "checker_instance")
    assert len(instances) == 1
    inst = instances[0]
    assert inst["semantic"]["name"] == "u_mutex"
    assert inst["semantic"]["path"] == "checker_corpus_top.u_mutex"
    assert inst["semantic"]["attributes"]["checker_name"] == "c_mutex"


def test_s28_has_checker_instance_edge(chk_graph):
    """The module emits a has_checker_instance edge to the instance node."""
    instances = _by_role(chk_graph, "checker_instance")
    assert instances
    inst_id = instances[0]["id"]
    modules = {n["semantic"]["path"]: n for n in _by_role(chk_graph, "module")}
    top = modules["checker_corpus_top"]
    edges = [e for e in chk_graph["edges"]
             if e["type"] == "has_checker_instance"
             and e["src"] == top["id"]
             and e["dst"] == inst_id]
    assert len(edges) == 1, f"expected 1 has_checker_instance edge, got {len(edges)}"


def test_s28_of_checker_edge_resolves(chk_graph):
    """The checker_instance node has an of_checker edge pointing to the
    checker declaration resolved via the shared name index."""
    instances = _by_role(chk_graph, "checker_instance")
    checkers = _by_role(chk_graph, "checker")
    assert instances and checkers
    inst_id = instances[0]["id"]
    chk_id = checkers[0]["id"]
    edges = [e for e in chk_graph["edges"]
             if e["type"] == "of_checker"
             and e["src"] == inst_id
             and e["dst"] == chk_id]
    assert len(edges) == 1, f"expected 1 of_checker edge, got {len(edges)}"


def test_s28_internal_property_parented_to_checker(chk_graph):
    """The PropertyDeclaration inside the checker attaches to the checker as
    parent — its hierarchical path is c_mutex.p_mutex, not the module."""
    props = [n for n in _by_role(chk_graph, "property")
             if n["semantic"]["name"] == "p_mutex"]
    assert len(props) == 1
    assert props[0]["semantic"]["path"] == "c_mutex.p_mutex"
    # has_property edge originates from the checker, not the module.
    chk = _by_role(chk_graph, "checker")[0]
    edges = [e for e in chk_graph["edges"]
             if e["type"] == "has_property"
             and e["src"] == chk["id"]
             and e["dst"] == props[0]["id"]]
    assert len(edges) == 1


def test_s28_internal_assertion_parented_to_checker(chk_graph):
    """The ConcurrentAssertionStatement inside the checker attaches to the
    checker as parent — its path is c_mutex.a_mutex."""
    asserts = [n for n in _by_role(chk_graph, "assertion")
               if n["semantic"]["name"] == "a_mutex"]
    assert len(asserts) == 1
    assert asserts[0]["semantic"]["path"] == "c_mutex.a_mutex"
    chk = _by_role(chk_graph, "checker")[0]
    edges = [e for e in chk_graph["edges"]
             if e["type"] == "has_assertion"
             and e["src"] == chk["id"]
             and e["dst"] == asserts[0]["id"]]
    assert len(edges) == 1


def test_s28_checker_name_index_registered(chk_graph):
    """The checker registers both qualified path and a ``checker:<name>``
    key in the shared name index so rule_s6 can resolve it in pass 2."""
    idx = chk_graph.get("semantic_name_index", {})
    assert "c_mutex" in idx
    assert "checker:c_mutex" in idx
    assert idx["c_mutex"] == idx["checker:c_mutex"]
