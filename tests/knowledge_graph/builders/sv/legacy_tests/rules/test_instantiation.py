"""S33 PrimitiveInstantiation / S43 DefParam: instantiation rule tests.

The S6 / S7 / S13 active rules are already exercised end-to-end by the
top.sv-backed test_invariants.py / test_roundtrip.py suites; S33 introduces
its own corpus (``prim_corpus.sv``) so the tests here focus on the new
behaviour:

* gate-type label (and / or / buf / not) stamped per instance
* multi-instance declaration fans out into one node per HierarchicalInstance
* positional port list captured
* optional ``#5`` delay attribute when present, absent otherwise
* ``has_primitive_instance`` containment edge from the enclosing module
* optional ``drives`` edge from the gate to its output net
"""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent.parent
PRIM = HERE / "corpus" / "prim_corpus.sv"
FIFO = HERE / "corpus" / "fifo.sv"
TOP = HERE / "corpus" / "top.sv"


@pytest.fixture(scope="module")
def prim_graph():
    from knowledge_graph.builders.sv.build import build_kg

    graph, _trees, _comp = build_kg([PRIM])
    return graph


def _primitive_nodes(graph):
    return [
        n for n in graph["nodes"]
        if n.get("semantic", {}).get("role") == "primitive_instance"
    ]


def _by_name(nodes, name):
    for n in nodes:
        if n["semantic"]["name"] == name:
            return n
    return None


def test_promotes_four_primitive_instances(prim_graph):
    """g_and / g_or / g_buf / g_not1 / g_not2 are all promoted."""
    prims = _primitive_nodes(prim_graph)
    names = sorted(n["semantic"]["name"] for n in prims)
    assert names == ["g_and", "g_buf", "g_not1", "g_not2", "g_or"]


def test_primitive_type_attribute(prim_graph):
    """Each instance carries the correct gate-type label."""
    prims = _primitive_nodes(prim_graph)
    types = {
        n["semantic"]["name"]: n["semantic"]["attributes"]["primitive"]
        for n in prims
    }
    assert types == {
        "g_and": "and",
        "g_or": "or",
        "g_buf": "buf",
        "g_not1": "not",
        "g_not2": "not",
    }


def test_multi_instance_fanout(prim_graph):
    """``not g_not1(...), g_not2(...);`` promotes BOTH HierarchicalInstance
    children — single PrimitiveInstantiation with two instances."""
    prims = _primitive_nodes(prim_graph)
    nots = [n for n in prims
            if n["semantic"]["attributes"]["primitive"] == "not"]
    assert len(nots) == 2
    paths = sorted(n["semantic"]["path"] for n in nots)
    assert paths == ["prim_demo.g_not1", "prim_demo.g_not2"]


def test_positional_ports_extracted(prim_graph):
    """Each instance's positional port list survives."""
    prims = _primitive_nodes(prim_graph)
    g_and = _by_name(prims, "g_and")
    assert g_and["semantic"]["attributes"]["ports"] == ["out_and", "a", "b"]
    g_not2 = _by_name(prims, "g_not2")
    assert g_not2["semantic"]["attributes"]["ports"] == ["n_b", "b"]


def test_delay_extracted_on_buf(prim_graph):
    """``buf #5 g_buf(...)`` captures the ``#5`` delay; other gates omit
    the ``delay`` key entirely (no surprise empty strings to filter)."""
    prims = _primitive_nodes(prim_graph)
    g_buf = _by_name(prims, "g_buf")
    assert g_buf["semantic"]["attributes"].get("delay") == "#5"
    g_and = _by_name(prims, "g_and")
    assert "delay" not in g_and["semantic"]["attributes"]


def test_has_primitive_instance_edges(prim_graph):
    """The enclosing module emits one ``has_primitive_instance`` edge per
    promoted instance node."""
    prims = _primitive_nodes(prim_graph)
    prim_ids = {n["id"] for n in prims}
    edges = [
        e for e in prim_graph["edges"]
        if e["type"] == "has_primitive_instance" and e["dst"] in prim_ids
    ]
    assert len(edges) == 5
    # All edges originate from the same parent module node.
    sources = {e["src"] for e in edges}
    assert len(sources) == 1
    module_node = next(
        n for n in prim_graph["nodes"]
        if n["id"] in sources and n.get("semantic", {}).get("role") == "module"
    )
    assert module_node["semantic"]["name"] == "prim_demo"


def test_drives_edge_to_output_port(prim_graph):
    """Gate primitives drive their first positional port. ``g_and`` drives
    the module output net ``out_and`` (resolvable via the name index)."""
    prims = _primitive_nodes(prim_graph)
    g_and = _by_name(prims, "g_and")
    out_drives = [
        e for e in prim_graph["edges"]
        if e["src"] == g_and["id"] and e["type"] == "drives"
    ]
    assert len(out_drives) == 1
    # Target node should be the ``out_and`` port (promoted by S1's ANSI-port
    # branch). Verify the name index entry was used.
    target_id = out_drives[0]["dst"]
    target = next(n for n in prim_graph["nodes"] if n["id"] == target_id)
    assert target["semantic"]["name"] == "out_and"


def test_rule_s33_metadata_registered():
    """The new rule is registered in the dispatch table with __rule_id__=S33."""
    import pyslang  # noqa: PLC0415

    from knowledge_graph.builders.sv.semantic.dispatch import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.PrimitiveInstantiation)
    assert fn is not None
    assert getattr(fn, "__rule_id__", None) == "S33"


def test_round_trip_primitive_instantiation():
    """PrimitiveInstantiationSyntax round-trips byte-equal through
    lift→emit→reparse, mirroring the round-trip oracle used by S6/S7/S13."""
    import pyslang  # noqa: PLC0415

    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.unlift import emit

    src = PRIM.read_text()
    tree = pyslang.SyntaxTree.fromText(src)
    assert not list(tree.diagnostics)
    graph = lift(tree)
    out = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(out)
    # Compare token text streams (the standard round-trip oracle).
    def _tokens(node, acc):
        if type(node).__name__ == "Token":
            for tr in node.trivia:
                acc.append(tr.getRawText())
            acc.append(node.rawText)
            return
        try:
            for c in node:
                _tokens(c, acc)
        except TypeError:
            pass

    orig: list[str] = []
    rt: list[str] = []
    _tokens(tree.root, orig)
    _tokens(reparsed.root, rt)
    assert orig == rt


# ---------------------------------------------------------------------------
# S43 — DefParam / DefParamAssignment promotion tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def top_graph():
    """Build a combined FIFO+TOP graph so defparam u_fifo.DEPTH resolves."""
    from knowledge_graph.builders.sv.build import build_kg

    graph, _trees, _comp = build_kg([FIFO, TOP])
    return graph


def test_defparam_override_edge_emitted(top_graph):
    """``defparam u_fifo.DEPTH = 8;`` emits a ``defparam_override`` edge
    from the enclosing ``top`` module node."""
    edges = [e for e in top_graph["edges"] if e["type"] == "defparam_override"]
    assert len(edges) >= 1, "expected at least one defparam_override edge"


# ---------------------------------------------------------------------------
# S49 — AnonymousProgram promotion tests
# ---------------------------------------------------------------------------

TB = HERE / "corpus" / "tb_fifo.sv"


@pytest.fixture(scope="module")
def tb_graph():
    """Build the tb_fifo graph which now contains an anonymous program block."""
    from knowledge_graph.builders.sv.build import build_kg

    graph, _trees, _comp = build_kg([TB])
    return graph


def _anon_program_nodes(graph):
    return [
        n for n in graph["nodes"]
        if n.get("semantic", {}).get("role") == "program"
        and n.get("semantic", {}).get("attributes", {}).get("anonymous") is True
    ]


def test_s49_promotes_anon_program_node(tb_graph):
    """An ``AnonymousProgram`` block is promoted with role=program and
    anonymous=True — it is a program in every semantic respect but has no
    declared name, so it carries a synthesised path key."""
    nodes = _anon_program_nodes(tb_graph)
    assert len(nodes) >= 1, "expected at least one anonymous program node"


def test_s49_anon_program_role(tb_graph):
    """The promoted node has role=program (same semantic role as S30 named
    programs) — anonymous programs are module-shaped containers."""
    nodes = _anon_program_nodes(tb_graph)
    roles = {n["semantic"]["role"] for n in nodes}
    assert roles == {"program"}


def test_s49_anon_program_anonymous_attribute(tb_graph):
    """The ``anonymous=True`` attribute distinguishes this node from a named
    S30 program so downstream queries can filter the two forms apart."""
    nodes = _anon_program_nodes(tb_graph)
    for n in nodes:
        assert n["semantic"]["attributes"]["anonymous"] is True


def test_s49_anon_program_path_key_deterministic(tb_graph):
    """The synthesised path key is non-empty and starts with ``__anon_program``
    so it is recognisable as synthetic while remaining deterministic."""
    nodes = _anon_program_nodes(tb_graph)
    for n in nodes:
        path = n["semantic"].get("path", "")
        assert path.startswith("__anon_program"), (
            f"expected path to start with __anon_program, got {path!r}"
        )


def test_s49_anon_program_child_decls_resolve_parent(tb_graph):
    """InitialBlock children inside the anonymous program attach to it as
    parent via the module_stack subtler variant (lesson 2). Verify that
    initial-block nodes whose path is prefixed with the anon-program path
    are promoted."""
    anon_nodes = _anon_program_nodes(tb_graph)
    assert anon_nodes, "prerequisite: at least one anon program"
    anon_path = anon_nodes[0]["semantic"]["path"]
    anon_id = anon_nodes[0]["id"]
    # Child nodes with paths under the anon_program path OR edges that go
    # from anon_program to a child node confirm parent resolution.
    child_edges = [
        e for e in tb_graph["edges"]
        if e["src"] == anon_id
    ]
    assert len(child_edges) >= 1, (
        "expected at least one edge from anonymous program node to a child"
    )


def test_s49_round_trip_anon_program():
    """AnonymousProgramSyntax round-trips byte-equal through lift→emit→reparse."""
    import pyslang  # noqa: PLC0415

    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.unlift import emit

    src = TB.read_text()
    tree = pyslang.SyntaxTree.fromText(src)
    assert not list(tree.diagnostics), "corpus must parse clean"
    graph = lift(tree)
    out = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(out)

    def _tokens(node, acc):
        if type(node).__name__ == "Token":
            for tr in node.trivia:
                acc.append(tr.getRawText())
            acc.append(node.rawText)
            return
        try:
            for c in node:
                _tokens(c, acc)
        except TypeError:
            pass

    orig: list[str] = []
    rt: list[str] = []
    _tokens(tree.root, orig)
    _tokens(reparsed.root, rt)
    assert orig == rt


def test_s49_rule_registered():
    """S49 is registered in the RULE_TABLE under AnonymousProgram."""
    import pyslang  # noqa: PLC0415

    from knowledge_graph.builders.sv.semantic.dispatch import RULE_TABLE

    fn = RULE_TABLE.get(pyslang.SyntaxKind.AnonymousProgram)
    assert fn is not None, "AnonymousProgram must have a RULE_TABLE entry"
    assert getattr(fn, "__rule_id__", None) == "S49"


def test_defparam_override_edge_payload_value(top_graph):
    """The ``defparam_override`` edge carries the literal RHS value text."""
    edges = [e for e in top_graph["edges"] if e["type"] == "defparam_override"]
    assert len(edges) >= 1
    edge = edges[0]
    # Payload key ``value`` must equal "8" (the integer literal in the corpus).
    assert edge.get("payload", {}).get("value") == "8", (
        f"expected payload.value='8', got {edge}"
    )


def test_defparam_override_source_is_module(top_graph):
    """The source of the ``defparam_override`` edge is the ``top`` module node."""
    edges = [e for e in top_graph["edges"] if e["type"] == "defparam_override"]
    assert edges
    src_id = edges[0]["src"]
    src_node = next(
        (n for n in top_graph["nodes"] if n["id"] == src_id), None
    )
    assert src_node is not None
    assert src_node.get("semantic", {}).get("role") == "module"
    assert src_node["semantic"]["name"] == "top"


def test_defparam_rule_registered():
    """DefParamAssignment (innermost kind) is registered with __rule_id__='S43'."""
    import pyslang  # noqa: PLC0415

    from knowledge_graph.builders.sv.semantic.dispatch import RULE_TABLE

    fn = RULE_TABLE.get(pyslang.SyntaxKind.DefParamAssignment)
    assert fn is not None, "DefParamAssignment not in RULE_TABLE"
    assert getattr(fn, "__rule_id__", None) == "S43"


def test_defparam_round_trip(top_graph):
    """top.sv (including the defparam line) round-trips byte-equal through
    lift → emit → reparse."""
    import pyslang  # noqa: PLC0415

    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.unlift import emit

    src = TOP.read_text()
    tree = pyslang.SyntaxTree.fromText(src)
    graph = lift(tree)
    out = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(out)

    def _tokens(node, acc):
        if type(node).__name__ == "Token":
            for tr in node.trivia:
                acc.append(tr.getRawText())
            acc.append(node.rawText)
            return
        try:
            for c in node:
                _tokens(c, acc)
        except TypeError:
            pass

    orig: list[str] = []
    rt: list[str] = []
    _tokens(tree.root, orig)
    _tokens(reparsed.root, rt)
    assert orig == rt


# ---------------------------------------------------------------------------
# S61 — BindTargetList promotion tests
# ---------------------------------------------------------------------------

FIFO_ASSERTS = HERE / "corpus" / "fifo_asserts.sv"


@pytest.fixture(scope="module")
def bind_target_graph():
    """Build a combined FIFO + TOP + FIFO_ASSERTS graph so the BindTargetList
    referencing ``u_fifo_a`` / ``u_fifo_b`` instances of ``top`` is resolvable
    via the cross-file semantic name index."""
    from knowledge_graph.builders.sv.build import build_kg

    graph, _trees, _comp = build_kg([FIFO, TOP, FIFO_ASSERTS])
    return graph


def _bind_target_edges(graph):
    return [e for e in graph["edges"] if e.get("type") == "bind_target"]


def test_s61_bind_target_edges_emitted(bind_target_graph):
    """The ``bind fifo : u_fifo_a, u_fifo_b, ghost_u`` directive emits one
    ``bind_target`` edge per named instance — three edges in total."""
    edges = _bind_target_edges(bind_target_graph)
    assert len(edges) == 3, (
        f"expected exactly 3 bind_target edges (u_fifo_a, u_fifo_b, ghost_u); "
        f"got {len(edges)}"
    )


def test_s61_bind_target_order_preserved(bind_target_graph):
    """The ordinal in each edge payload reflects the source order of the
    target-list identifiers — ``u_fifo_a`` is 0, ``u_fifo_b`` is 1,
    ``ghost_u`` is 2."""
    edges = _bind_target_edges(bind_target_graph)
    ordered = sorted(edges, key=lambda e: e["payload"]["index"])
    names = [e["payload"]["target"] for e in ordered]
    assert names == ["u_fifo_a", "u_fifo_b", "ghost_u"], names


def test_s61_resolved_instance_targets(bind_target_graph):
    """``u_fifo_a`` and ``u_fifo_b`` are real instances of ``fifo`` inside
    ``top`` and resolve via the name index to the HierarchicalInstance node
    id — the edge dst is the resolved gid, payload has no ``unresolved``."""
    idx = bind_target_graph.get("semantic_name_index", {})
    u_a_gid = idx.get("top.u_fifo_a")
    u_b_gid = idx.get("top.u_fifo_b")
    assert u_a_gid is not None and u_b_gid is not None
    edges = _bind_target_edges(bind_target_graph)
    by_name = {e["payload"]["target"]: e for e in edges}
    assert by_name["u_fifo_a"]["dst"] == u_a_gid
    assert by_name["u_fifo_b"]["dst"] == u_b_gid
    assert not by_name["u_fifo_a"]["payload"].get("unresolved")
    assert not by_name["u_fifo_b"]["payload"].get("unresolved")


def test_s61_unresolved_fallback(bind_target_graph):
    """``ghost_u`` does not exist anywhere in the name index — the edge dst
    falls back to ``_unresolved.ghost_u`` and payload carries
    ``unresolved=True``."""
    edges = _bind_target_edges(bind_target_graph)
    by_name = {e["payload"]["target"]: e for e in edges}
    ghost = by_name["ghost_u"]
    assert ghost["dst"] == "_unresolved.ghost_u"
    assert ghost["payload"].get("unresolved") is True


def test_s61_edge_source_is_binder_module(bind_target_graph):
    """The src of each ``bind_target`` edge is the binder module node
    (``fifo_asserts``) — same source semantics as S13's ``bound_into``."""
    idx = bind_target_graph.get("semantic_name_index", {})
    binder_gid = idx.get("module:fifo_asserts") or idx.get("fifo_asserts")
    assert binder_gid is not None
    edges = _bind_target_edges(bind_target_graph)
    for e in edges:
        assert e["src"] == binder_gid, (
            f"expected src={binder_gid}, got {e['src']} for target "
            f"{e['payload'].get('target')!r}"
        )


def test_s61_rule_metadata_registered():
    """BindTargetList is registered in the dispatch table with __rule_id__=S61
    as an ownership marker (lesson 4 edge-only kind — stub function)."""
    import pyslang  # noqa: PLC0415

    from knowledge_graph.builders.sv.semantic.dispatch import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.BindTargetList)
    assert fn is not None
    assert getattr(fn, "__rule_id__", None) == "S61"


def test_s61_round_trip_bind_target_list():
    """BindTargetListSyntax + the surrounding BindDirective round-trip
    byte-equal through lift→emit→reparse — lesson 4 edges don't perturb the
    structural lift."""
    import pyslang  # noqa: PLC0415

    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.unlift import emit

    src = FIFO_ASSERTS.read_text()
    tree = pyslang.SyntaxTree.fromText(src)
    assert not list(tree.diagnostics)
    graph = lift(tree)
    out = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(out)

    def _tokens(node, acc):
        if type(node).__name__ == "Token":
            for tr in node.trivia:
                acc.append(tr.getRawText())
            acc.append(node.rawText)
            return
        try:
            for c in node:
                _tokens(c, acc)
        except TypeError:
            pass

    orig: list[str] = []
    rt: list[str] = []
    _tokens(tree.root, orig)
    _tokens(reparsed.root, rt)
    assert orig == rt
