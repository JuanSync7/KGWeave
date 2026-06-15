"""Tests for S68 — PortConcatenation promotion.

PortConcatenationSyntax is the ``{a, b}`` curly-grouped port reference inside
non-ANSI port lists, e.g. ``module legacy_implicit_demo(a, b, {x, y});``.
The concatenation is one external port that bundles multiple internal nets.

S68 promotes the PortConcatenationSyntax itself as ``role=port_concat``:

* Path key: ``<module>.__port_concat_<offset>__`` (the concat has no name —
  ``<offset>`` is a per-module monotonically-increasing index, matching the
  convention used by other anonymous promotions like S19 proc_assign).
* Edge: ``has_port`` from the enclosing module to the concat node (the
  concat IS one external port).
* Edge: ``groups_port_ref`` from the concat node to each member
  PortReference's gid (S67 promotes those members at
  ``<module>.port_reference.<name>``; that path-keying does NOT change).
* The S67 PortReference members under the concat remain queryable as before
  (this rule must not regress S67's behavior in legacy_implicit_demo).

Exercised by ``{x, y}`` in ``legacy_implicit_demo`` (corpus/fifo.sv).
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
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return tree, comp, graph


def _by_role(graph, role):
    from knowledge_graph.builders.sv.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph)
            if n.get("semantic", {}).get("role") == role]


def _port_concat_nodes(graph):
    return [n for n in _by_role(graph, "port_concat")
            if n.get("kind", "").endswith("PortConcatenation")]


def test_s68_port_concat_role_registered(fixture_bundle):
    """The single ``{x, y}`` entry in legacy_implicit_demo surfaces as
    role=port_concat (PromotedKind=PortConcatenation)."""
    _t, _c, graph = fixture_bundle
    concats = _port_concat_nodes(graph)
    assert len(concats) == 1, (
        f"expected exactly 1 PortConcatenation node, got {len(concats)}"
    )


def test_s68_port_concat_path_under_module(fixture_bundle):
    """The port_concat path lives under its enclosing module with an
    anonymous synthetic suffix (the concat has no source name)."""
    _t, _c, graph = fixture_bundle
    concats = _port_concat_nodes(graph)
    assert len(concats) == 1
    path = concats[0]["semantic"]["path"]
    assert path.startswith("legacy_implicit_demo."), (
        f"unexpected port_concat path: {path}"
    )
    assert "__port_concat_" in path, (
        f"port_concat path missing synthetic suffix: {path}"
    )


def test_s68_has_port_edge_from_module(fixture_bundle):
    """The concat IS one external port externally — module has a has_port
    edge to it."""
    _t, _c, graph = fixture_bundle
    concats = _port_concat_nodes(graph)
    assert len(concats) == 1
    concat_gid = concats[0]["id"]
    # Look up the module node id.
    mods = {n["semantic"]["name"]: n for n in _by_role(graph, "module")}
    assert "legacy_implicit_demo" in mods
    mod_gid = mods["legacy_implicit_demo"]["id"]
    has_port = [e for e in graph["edges"]
                if e.get("src") == mod_gid
                and e.get("dst") == concat_gid
                and e.get("type") == "has_port"]
    assert len(has_port) == 1, (
        f"expected has_port edge from legacy_implicit_demo to concat: "
        f"{has_port}"
    )


def test_s68_groups_port_ref_edges_to_members(fixture_bundle):
    """The concat groups its PortReference members via groups_port_ref
    edges — one per member (x, y)."""
    _t, _c, graph = fixture_bundle
    concats = _port_concat_nodes(graph)
    assert len(concats) == 1
    concat_gid = concats[0]["id"]
    groups = [e for e in graph["edges"]
              if e.get("src") == concat_gid
              and e.get("type") == "groups_port_ref"]
    assert len(groups) == 2, (
        f"expected 2 groups_port_ref edges from concat, got {len(groups)}"
    )
    # Resolve the targeted PortReference gids back to their names.
    refs_by_id = {n["id"]: n for n in _by_role(graph, "port_reference")}
    member_names = {refs_by_id[e["dst"]]["semantic"]["name"]
                    for e in groups if e["dst"] in refs_by_id}
    assert member_names == {"x", "y"}, (
        f"concat members mismatch: {member_names}"
    )


def test_s68_s67_members_still_emit(fixture_bundle):
    """S67's promotion of the concat-member PortReferences must not regress
    — both ``x`` and ``y`` still surface as role=port_reference at the
    documented sub-namespace path."""
    from knowledge_graph.builders.sv.semantic import queryable_nodes

    _t, _c, graph = fixture_bundle
    refs = [n for n in queryable_nodes(graph)
            if n.get("semantic", {}).get("role") == "port_reference"
            and n.get("kind", "").endswith("PortReference")]
    paths = {r["semantic"]["path"] for r in refs}
    assert "legacy_implicit_demo.port_reference.x" in paths
    assert "legacy_implicit_demo.port_reference.y" in paths


def test_s68_does_not_duplicate_module_ports(fixture_bundle):
    """The S66 implicit-bare ports (a, b) stay as exactly 2 role=port nodes
    under legacy_implicit_demo — S68 does not retroactively spawn role=port
    nodes for the concat-member identifiers."""
    _t, _c, graph = fixture_bundle
    ports = [n for n in _by_role(graph, "port")
             if n["semantic"].get("path", "").startswith(
                 "legacy_implicit_demo.")
             and n.get("kind", "").endswith("ImplicitNonAnsiPort")]
    assert len(ports) == 2, (
        f"S68 unexpectedly perturbed S66 port nodes: {len(ports)} != 2"
    )


def test_s68_roundtrip(fixture_bundle):
    """Promotion must not perturb the token stream — emit() reproduces source."""
    _t, _c, graph = fixture_bundle
    from knowledge_graph.builders.sv.unlift import emit
    assert emit(graph) == SRC.read_text()
