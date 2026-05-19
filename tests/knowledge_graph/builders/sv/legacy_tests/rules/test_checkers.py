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
CHK = HERE / "corpus" / "checker_corpus.sv"


@pytest.fixture(scope="module")
def chk_graph():
    text = CHK.read_text()
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


def test_s28_checker_declaration_promoted(chk_graph):
    """c_mutex is promoted with role=checker at compilation-unit scope."""
    checkers = _by_role(chk_graph, "checker")
    assert len(checkers) == 1
    c = checkers[0]
    assert c["semantic"]["name"] == "c_mutex"
    assert c["semantic"]["path"] == "c_mutex"


def test_s28_checker_instance_promoted(chk_graph):
    """Two checker_instance nodes promote under checker_corpus_top:
    ``u_mutex`` at module scope (via rule_s6 reclassification of a
    HierarchyInstantiation) and ``u_proc`` at procedural scope inside
    the ``initial`` block (via S28's CheckerInstantiation branch, with
    the S79 wrapper staying CONTAINER). Both stamp ``checker_name``."""
    instances = _by_role(chk_graph, "checker_instance")
    assert len(instances) == 2
    by_name = {inst["semantic"]["name"]: inst for inst in instances}
    assert set(by_name) == {"u_mutex", "u_proc"}
    assert by_name["u_mutex"]["semantic"]["path"] == "checker_corpus_top.u_mutex"
    assert by_name["u_proc"]["semantic"]["path"] == "checker_corpus_top.u_proc"
    for inst in instances:
        assert inst["semantic"]["attributes"]["checker_name"] == "c_mutex"


def test_s28_has_checker_instance_edge(chk_graph):
    """The module emits a has_checker_instance edge to each instance node."""
    instances = _by_role(chk_graph, "checker_instance")
    assert instances
    modules = {n["semantic"]["path"]: n for n in _by_role(chk_graph, "module")}
    top = modules["checker_corpus_top"]
    for inst in instances:
        inst_id = inst["id"]
        edges = [e for e in chk_graph["edges"]
                 if e["type"] == "has_checker_instance"
                 and e["src"] == top["id"]
                 and e["dst"] == inst_id]
        assert len(edges) == 1, (
            f"expected 1 has_checker_instance edge to "
            f"{inst['semantic']['name']}, got {len(edges)}"
        )


def test_s28_of_checker_edge_resolves(chk_graph):
    """Each checker_instance node has an of_checker edge to the resolved
    checker declaration."""
    instances = _by_role(chk_graph, "checker_instance")
    checkers = _by_role(chk_graph, "checker")
    assert instances and checkers
    chk_id = checkers[0]["id"]
    for inst in instances:
        inst_id = inst["id"]
        edges = [e for e in chk_graph["edges"]
                 if e["type"] == "of_checker"
                 and e["src"] == inst_id
                 and e["dst"] == chk_id]
        assert len(edges) == 1, (
            f"expected 1 of_checker edge from "
            f"{inst['semantic']['name']}, got {len(edges)}"
        )


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


# ---------------------------------------------------------------------------
# S62 — CheckerDataDeclaration (rand-prefixed checker-local data decls).
# ---------------------------------------------------------------------------


def test_s62_checker_data_nodes_promoted(chk_graph):
    """rand-prefixed checker-local data decls surface as role=checker_data
    nodes — ``rand bit r_flag;`` plus the fan-out ``rand bit [1:0] r_mode,
    r_dir;`` together yield three checker_data nodes attached to c_mutex."""
    cds = _by_role(chk_graph, "checker_data")
    names = sorted(n["semantic"]["name"] for n in cds)
    assert names == ["r_dir", "r_flag", "r_mode"], names
    paths = sorted(n["semantic"]["path"] for n in cds)
    assert paths == ["c_mutex.r_dir", "c_mutex.r_flag", "c_mutex.r_mode"], paths


def test_s62_checker_data_attrs(chk_graph):
    """data_type, has_initializer, and is_rand are stamped per declarator.
    All three rand entries carry is_rand=True; types are bit / bit[1:0]."""
    by_name = {n["semantic"]["name"]: n for n in _by_role(chk_graph, "checker_data")}
    r_flag = by_name["r_flag"]["semantic"]["attributes"]
    assert r_flag["is_rand"] is True
    assert r_flag["has_initializer"] is False
    assert r_flag["data_type"].strip().startswith("bit")
    assert "[" not in r_flag["data_type"]  # no packed dim on r_flag
    r_mode = by_name["r_mode"]["semantic"]["attributes"]
    assert r_mode["is_rand"] is True
    assert "[" in r_mode["data_type"] and "1" in r_mode["data_type"]
    # r_mode and r_dir share the same data_type (fan-out preserves type_text).
    assert r_mode["data_type"] == by_name["r_dir"]["semantic"]["attributes"]["data_type"]


def test_s62_checker_data_fanout_multi_declarator(chk_graph):
    """A single ``rand bit [1:0] r_mode, r_dir;`` produces two distinct
    checker_data nodes (S38-style fan-out — canonical + synthetic sibling)."""
    cds = [n for n in _by_role(chk_graph, "checker_data")
           if n["semantic"]["name"] in ("r_mode", "r_dir")]
    assert len(cds) == 2
    # The two nodes have distinct ids.
    assert cds[0]["id"] != cds[1]["id"]


def test_s62_has_checker_data_edges(chk_graph):
    """Each checker_data node has exactly one has_checker_data edge from
    the enclosing c_mutex checker."""
    chk = _by_role(chk_graph, "checker")[0]
    cds = _by_role(chk_graph, "checker_data")
    assert cds
    for cd in cds:
        edges = [e for e in chk_graph["edges"]
                 if e["type"] == "has_checker_data"
                 and e["src"] == chk["id"]
                 and e["dst"] == cd["id"]]
        assert len(edges) == 1, (cd["semantic"]["name"], len(edges))


def test_s62_is_rand_discrimination(chk_graph):
    """is_rand on a checker_data is True; the non-rand DataDeclarations
    inside the same checker (``logic loc_a, loc_b;`` / ``bit [3:0] cnt;``)
    are NOT promoted as checker_data — they remain plain nets."""
    cds = _by_role(chk_graph, "checker_data")
    cd_names = {n["semantic"]["name"] for n in cds}
    assert "loc_a" not in cd_names
    assert "loc_b" not in cd_names
    assert "cnt" not in cd_names
    # All checker_data entries have is_rand=True (this is the LRM-defined
    # discriminator — only ``rand`` decls become CheckerDataDeclaration).
    for cd in cds:
        assert cd["semantic"]["attributes"]["is_rand"] is True
    # The non-rand checker-local decls still surface (as nets) — confirm
    # they didn't get accidentally suppressed.
    nets = [n for n in chk_graph["nodes"]
            if n.get("semantic", {}).get("role") == "net"
            and n["semantic"]["path"].startswith("c_mutex.")]
    net_names = {n["semantic"]["name"] for n in nets}
    assert {"loc_a", "loc_b", "cnt"} <= net_names


def test_s62_checker_data_name_index(chk_graph):
    """Each checker_data node is registered in the name index at its
    qualified path so consumers can resolve ``c_mutex.r_flag``."""
    idx = chk_graph.get("semantic_name_index", {})
    cds = _by_role(chk_graph, "checker_data")
    for cd in cds:
        path = cd["semantic"]["path"]
        assert path in idx
        assert idx[path] == cd["id"]


def test_s62_checker_corpus_roundtrips():
    """checker_corpus.sv survives the lift → unlift byte-equal round-trip
    after the S62 corpus extension (logic/bit/rand decls added)."""
    text = CHK.read_text()
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.unlift import emit

    tree = pyslang.SyntaxTree.fromText(text)
    graph = lift(tree)
    reconstructed = emit(graph)
    assert reconstructed == text
