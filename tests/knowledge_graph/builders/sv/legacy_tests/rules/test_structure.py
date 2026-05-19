"""Tests for the structure-rule family.

Currently exercises S55 — promotion of non-ANSI PortDeclaration bodies in
``nonansi_demo`` (corpus/fifo.sv). S1 ImplicitAnsiPort coverage already lives
in test_dataflow.py; this file is the home for future structural-rule tests.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def fixture_bundle():
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return tree, comp, graph


def _by_role(graph, role):
    from research.ast_experiment.src.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph)
            if n.get("semantic", {}).get("role") == role]


def _s55_body_ports(graph):
    """S55 binds at DeclaratorSyntax; filter out S66 ImplicitNonAnsiPort
    header twins that share the same <module>.<name> path."""
    return [p for p in _by_role(graph, "port")
            if p.get("kind", "").endswith("Declarator")]


def test_s55_nonansi_port_decls_promoted(fixture_bundle):
    """Every PortDeclaration Declarator in nonansi_demo surfaces as role=port."""
    _t, _c, graph = fixture_bundle
    ports = _s55_body_ports(graph)
    names = {p["semantic"]["name"] for p in ports
             if p["semantic"]["path"].startswith("nonansi_demo.")}
    assert names == {"a", "b", "c", "d", "e", "f"}, (
        f"non-ANSI port names mismatch: {names}"
    )


def test_s55_direction_attrs(fixture_bundle):
    """Each non-ANSI port carries the correct direction attribute."""
    _t, _c, graph = fixture_bundle
    ports = {p["semantic"]["name"]: p for p in _s55_body_ports(graph)
             if p["semantic"]["path"].startswith("nonansi_demo.")}
    expected = {"a": "input", "b": "output", "c": "inout",
                "d": "input", "e": "output", "f": "output"}
    for name, want in expected.items():
        attrs = ports[name]["semantic"].get("attributes", {})
        assert attrs.get("direction") == want, (
            f"{name}: expected direction={want}, got {attrs}"
        )


def test_s55_has_port_edges_from_enclosing_module(fixture_bundle):
    """Each non-ANSI body port has exactly one inbound has_port edge from
    the enclosing nonansi_demo module."""
    _t, _c, graph = fixture_bundle
    mods = {m["semantic"]["name"]: m for m in _by_role(graph, "module")}
    mod_id = mods["nonansi_demo"]["id"]
    ports = [p for p in _s55_body_ports(graph)
             if p["semantic"]["path"].startswith("nonansi_demo.")]
    assert len(ports) == 6
    for p in ports:
        incoming = [e for e in graph["edges"]
                    if e["type"] == "has_port" and e["dst"] == p["id"]]
        assert len(incoming) == 1, (
            f"{p['semantic']['path']}: has_port incoming = {len(incoming)}"
        )
        assert incoming[0]["src"] == mod_id, (
            f"{p['semantic']['path']}: has_port src is not nonansi_demo"
        )


def test_s55_no_duplicate_body_port_nodes(fixture_bundle):
    """No two S55 body-port nodes share a path inside nonansi_demo. S66
    header twins (ImplicitNonAnsiPort kind) coexist on the same path by
    design — the header view and the body view are separate queryable
    nodes."""
    _t, _c, graph = fixture_bundle
    paths = [p["semantic"]["path"] for p in _s55_body_ports(graph)
             if p["semantic"]["path"].startswith("nonansi_demo.")]
    assert len(paths) == len(set(paths)), (
        f"duplicate S55 body port paths: {sorted(paths)}"
    )


def test_s55_does_not_regress_ansi_ports(fixture_bundle):
    """fifo's ANSI ports (S1 path) keep their full set after S55."""
    _t, _c, graph = fixture_bundle
    fifo_ports = {p["semantic"]["name"] for p in _by_role(graph, "port")
                  if p["semantic"]["path"].startswith("fifo.")}
    assert fifo_ports == {
        "clk", "rst_n", "push", "pop", "din", "dout",
        "full", "empty", "status",
    }


def test_s55_port_decl_declarators_not_promoted_as_net(fixture_bundle):
    """The Declarators under PortDeclarationSyntax must NOT also surface as
    role=net — only as role=port."""
    _t, _c, graph = fixture_bundle
    nets = {n["semantic"]["name"] for n in _by_role(graph, "net")
            if n["semantic"]["path"].startswith("nonansi_demo.")}
    assert nets == set(), (
        f"non-ANSI port names leaked into role=net: {nets}"
    )


def test_s55_roundtrip(fixture_bundle):
    """Promotion must not perturb token stream — round-trip stays byte-equal."""
    tree, _c, graph = fixture_bundle
    from research.ast_experiment.src.unlift import emit

    emitted = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)
