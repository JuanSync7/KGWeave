"""S19: ProceduralAssign / ProceduralDeassign promotion.

The corpus's ``fifo_asserts.sv`` includes ``module proc_assign_demo`` with an
always block that contains both a ``assign r = din;`` (procedural
continuous assign) and a ``deassign r;`` statement. S19 promotes each
``ProceduralAssignStatementSyntax`` and ``ProceduralDeassignStatementSyntax``
node to ``role="procedural_assign"`` / ``role="procedural_deassign"`` under
the enclosing module (NOT the always block), attaches a
``has_procedural_assign`` edge from the parent module, stamps
``attributes["lhs"]`` with the structurally extracted target identifier,
and — when the LHS resolves via the shared name index — emits a
``drives`` edge to the target net.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
BIND = HERE / "corpus" / "fifo_asserts.sv"


@pytest.fixture(scope="module")
def bind_graph():
    text = BIND.read_text()
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


def test_s19_procedural_assign_promoted(bind_graph):
    """The ``assign r = din;`` statement is promoted with role
    procedural_assign and a path under the parent module."""
    pas = _by_role(bind_graph, "procedural_assign")
    assert len(pas) == 1, f"expected 1 procedural_assign, got {len(pas)}"
    node = pas[0]
    assert node["semantic"]["path"].startswith("proc_assign_demo.")
    assert node["semantic"]["attributes"]["lhs"] == "r"


def test_s19_procedural_deassign_promoted(bind_graph):
    """The ``deassign r;`` statement is promoted with role
    procedural_deassign and the same LHS."""
    pds = _by_role(bind_graph, "procedural_deassign")
    assert len(pds) == 1, f"expected 1 procedural_deassign, got {len(pds)}"
    node = pds[0]
    assert node["semantic"]["path"].startswith("proc_assign_demo.")
    assert node["semantic"]["attributes"]["lhs"] == "r"


def test_s19_parent_is_module_not_always_block(bind_graph):
    """The has_procedural_assign edge runs from the enclosing module
    (proc_assign_demo) — never from the AlwaysBlock or SequentialBlock."""
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules
                   if m["semantic"]["name"] == "proc_assign_demo"), None)
    assert parent is not None, "proc_assign_demo module not promoted"
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_procedural_assign"
             and e["src"] == parent["id"]]
    assert len(edges) == 2, (
        f"expected 2 has_procedural_assign edges from proc_assign_demo, "
        f"got {len(edges)}"
    )


def test_s19_name_index_registers_paths(bind_graph):
    """Both synthesized paths are registered in semantic_name_index so
    downstream rules can resolve procedural assigns by qualified name."""
    idx = bind_graph.get("semantic_name_index", {})
    pas = _by_role(bind_graph, "procedural_assign")
    pds = _by_role(bind_graph, "procedural_deassign")
    for n in pas + pds:
        path = n["semantic"]["path"]
        assert path in idx, f"name_index missing {path}"


def test_s19_drives_edge_resolves_to_net(bind_graph):
    """The procedural-assign LHS ``r`` resolves to the local net
    ``proc_assign_demo.r`` via the shared name index, so a drives edge
    is emitted from the procedural_assign node to the net."""
    pas = _by_role(bind_graph, "procedural_assign")
    assert pas, "no procedural_assign node"
    pa = pas[0]
    nets = [n for n in _by_role(bind_graph, "net")
            if n["semantic"]["path"] == "proc_assign_demo.r"]
    assert nets, "proc_assign_demo.r net not promoted"
    net_id = nets[0]["id"]
    drives = [e for e in bind_graph["edges"]
              if e["type"] == "drives"
              and e["src"] == pa["id"]
              and e["dst"] == net_id]
    assert len(drives) == 1, (
        f"expected one drives edge procedural_assign→r, got {len(drives)}"
    )


# ---------------------------------------------------------------------------
# S20 — ProceduralForce / ProceduralRelease
#
# ``force_release_demo`` in fifo_asserts.sv has one ``force r = 8'hAA;`` and
# one ``release r;`` inside an always block. pyslang reuses the same
# ProceduralAssign/Deassign syntax classes for force/release; the variant is
# carried only by ``.kind``. S20 promotes them with their own role labels
# ("procedural_force" / "procedural_release") and a dedicated containment
# edge type ``has_procedural_force`` (shared across both kinds, with the
# role attribute differentiating them).
# ---------------------------------------------------------------------------


def test_s20_procedural_force_promoted(bind_graph):
    """The ``force r = 8'hAA;`` statement is promoted with role
    procedural_force and a path under the parent module."""
    pfs = _by_role(bind_graph, "procedural_force")
    assert len(pfs) == 1, f"expected 1 procedural_force, got {len(pfs)}"
    node = pfs[0]
    assert node["semantic"]["path"].startswith("force_release_demo.")
    assert node["semantic"]["attributes"]["lhs"] == "r"


def test_s20_procedural_release_promoted(bind_graph):
    """The ``release r;`` statement is promoted with role
    procedural_release and the same LHS."""
    prs = _by_role(bind_graph, "procedural_release")
    assert len(prs) == 1, f"expected 1 procedural_release, got {len(prs)}"
    node = prs[0]
    assert node["semantic"]["path"].startswith("force_release_demo.")
    assert node["semantic"]["attributes"]["lhs"] == "r"


def test_s20_parent_is_module_not_always_block(bind_graph):
    """The has_procedural_force edge runs from the enclosing module
    (force_release_demo) — never from the AlwaysBlock. One edge per
    force/release statement (two total)."""
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules
                   if m["semantic"]["name"] == "force_release_demo"), None)
    assert parent is not None, "force_release_demo module not promoted"
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_procedural_force"
             and e["src"] == parent["id"]]
    assert len(edges) == 2, (
        f"expected 2 has_procedural_force edges from force_release_demo, "
        f"got {len(edges)}"
    )


def test_s20_name_index_registers_paths(bind_graph):
    """Force/release synthesized paths are registered in semantic_name_index."""
    idx = bind_graph.get("semantic_name_index", {})
    pfs = _by_role(bind_graph, "procedural_force")
    prs = _by_role(bind_graph, "procedural_release")
    for n in pfs + prs:
        path = n["semantic"]["path"]
        assert path in idx, f"name_index missing {path}"


def test_s20_drives_edge_resolves_to_net(bind_graph):
    """The procedural-force LHS ``r`` resolves to the local net
    ``force_release_demo.r`` via the shared name index, so a drives edge
    is emitted from the procedural_force node to the net."""
    pfs = _by_role(bind_graph, "procedural_force")
    assert pfs, "no procedural_force node"
    pf = pfs[0]
    nets = [n for n in _by_role(bind_graph, "net")
            if n["semantic"]["path"] == "force_release_demo.r"]
    assert nets, "force_release_demo.r net not promoted"
    net_id = nets[0]["id"]
    drives = [e for e in bind_graph["edges"]
              if e["type"] == "drives"
              and e["src"] == pf["id"]
              and e["dst"] == net_id]
    assert len(drives) == 1, (
        f"expected one drives edge procedural_force→r, got {len(drives)}"
    )


def test_s20_assign_and_force_distinct_roles(bind_graph):
    """S19's procedural_assign and S20's procedural_force are distinct roles —
    confirming the pass-1 branch discriminates by ``.kind`` rather than by
    the (shared) syntax class name."""
    assert len(_by_role(bind_graph, "procedural_assign")) == 1
    assert len(_by_role(bind_graph, "procedural_force")) == 1
    assert len(_by_role(bind_graph, "procedural_deassign")) == 1
    assert len(_by_role(bind_graph, "procedural_release")) == 1


# ---------------------------------------------------------------------------
# S21 — BlockingEventTriggerStatement / NonblockingEventTriggerStatement
#
# ``event_trigger_demo`` in fifo_asserts.sv declares two named events
# (ev_done, ev_ready) and fires one with ``-> ev_done;`` (blocking) and one
# with ``->> ev_ready;`` (nonblocking) inside an always block. pyslang
# surfaces both with the single class ``EventTriggerStatementSyntax`` —
# only ``.kind`` discriminates the variant. S21 promotes each with role
# ``event_trigger`` and a dedicated ``has_event_trigger`` containment edge
# from the parent module; the ``blocking`` attribute carries the variant.
# ---------------------------------------------------------------------------


def test_s21_blocking_event_trigger_promoted(bind_graph):
    """The ``-> ev_done;`` statement is promoted with role event_trigger,
    blocking=True, and event_name=ev_done."""
    triggers = [n for n in _by_role(bind_graph, "event_trigger")
                if n["semantic"]["attributes"]["blocking"] is True]
    assert len(triggers) == 1, (
        f"expected 1 blocking event_trigger, got {len(triggers)}"
    )
    node = triggers[0]
    assert node["semantic"]["path"].startswith("event_trigger_demo.")
    assert node["semantic"]["attributes"]["event_name"] == "ev_done"


def test_s21_nonblocking_event_trigger_promoted(bind_graph):
    """The ``->> ev_ready;`` statement is promoted with role event_trigger,
    blocking=False, and event_name=ev_ready."""
    triggers = [n for n in _by_role(bind_graph, "event_trigger")
                if n["semantic"]["attributes"]["blocking"] is False]
    assert len(triggers) == 1, (
        f"expected 1 nonblocking event_trigger, got {len(triggers)}"
    )
    node = triggers[0]
    assert node["semantic"]["path"].startswith("event_trigger_demo.")
    assert node["semantic"]["attributes"]["event_name"] == "ev_ready"


def test_s21_parent_is_module_not_always_block(bind_graph):
    """The has_event_trigger edge runs from the enclosing module
    (event_trigger_demo), one per trigger statement (two total)."""
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules
                   if m["semantic"]["name"] == "event_trigger_demo"), None)
    assert parent is not None, "event_trigger_demo module not promoted"
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_event_trigger"
             and e["src"] == parent["id"]]
    assert len(edges) == 2, (
        f"expected 2 has_event_trigger edges from event_trigger_demo, "
        f"got {len(edges)}"
    )


def test_s21_name_index_registers_paths(bind_graph):
    """Both synthesized trigger paths are registered in the
    semantic_name_index so downstream rules can resolve them."""
    idx = bind_graph.get("semantic_name_index", {})
    triggers = _by_role(bind_graph, "event_trigger")
    assert len(triggers) == 2
    for n in triggers:
        path = n["semantic"]["path"]
        assert path in idx, f"name_index missing {path}"


def test_s21_triggers_edge_resolves_to_event(bind_graph):
    """The event_name on each trigger resolves to the corresponding
    declarator in the parent module (events surface as nets in pass-1),
    so a ``triggers`` edge is emitted from the trigger node to the
    event node."""
    triggers = _by_role(bind_graph, "event_trigger")
    names = {n["semantic"]["attributes"]["event_name"] for n in triggers}
    assert names == {"ev_done", "ev_ready"}
    nets = {n["semantic"]["path"]: n["id"]
            for n in _by_role(bind_graph, "net")
            if n["semantic"]["path"].startswith("event_trigger_demo.")}
    for tr in triggers:
        ev_name = tr["semantic"]["attributes"]["event_name"]
        ev_path = f"event_trigger_demo.{ev_name}"
        assert ev_path in nets, f"event {ev_path} not in promoted nets"
        ev_id = nets[ev_path]
        drives = [e for e in bind_graph["edges"]
                  if e["type"] == "triggers"
                  and e["src"] == tr["id"]
                  and e["dst"] == ev_id]
        assert len(drives) == 1, (
            f"expected one triggers edge for {tr['semantic']['path']}→{ev_path}"
        )


# ---------------------------------------------------------------------------
# S42 — LetDeclaration
#
# ``let_decl_demo`` in fifo_asserts.sv declares three let expressions:
#   let nonzero(x) = x != 0;    -- 1 port
#   let in_range(a, b) = a < b; -- 2 ports
#   let always_true() = 1;      -- 0 ports
# S42 promotes each as role=let_decl under the enclosing module, emits a
# has_let edge from the module, stamps attributes["port_count"] with the
# port count, and registers the qualified path in the name_index.
# ---------------------------------------------------------------------------


def test_s42_let_decl_promoted(bind_graph):
    """All three let declarations in let_decl_demo are promoted with
    role=let_decl and paths rooted at the enclosing module."""
    lets = _by_role(bind_graph, "let_decl")
    names = {n["semantic"]["name"] for n in lets}
    assert {"nonzero", "in_range", "always_true"} <= names, (
        f"expected nonzero/in_range/always_true in promoted lets; got {names}"
    )
    for n in lets:
        if n["semantic"]["name"] in {"nonzero", "in_range", "always_true"}:
            assert n["semantic"]["path"].startswith("let_decl_demo."), (
                f"path should be under let_decl_demo, got {n['semantic']['path']}"
            )


def test_s42_port_count_attribute(bind_graph):
    """port_count attribute matches the declared arity of each let."""
    lets = {n["semantic"]["name"]: n
            for n in _by_role(bind_graph, "let_decl")
            if n["semantic"]["path"].startswith("let_decl_demo.")}
    assert lets["nonzero"]["semantic"]["attributes"]["port_count"] == 1
    assert lets["in_range"]["semantic"]["attributes"]["port_count"] == 2
    assert lets["always_true"]["semantic"]["attributes"]["port_count"] == 0


def test_s42_has_let_edge_from_module(bind_graph):
    """has_let edges run from the let_decl_demo module node to each let node."""
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules
                   if m["semantic"]["name"] == "let_decl_demo"), None)
    assert parent is not None, "let_decl_demo module not promoted"
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_let"
             and e["src"] == parent["id"]]
    # S77 added a fourth parameterised let ``bounded`` to the same module.
    assert len(edges) == 4, (
        f"expected 4 has_let edges from let_decl_demo, got {len(edges)}"
    )


def test_s42_name_index_registration(bind_graph):
    """All three qualified let paths are registered in semantic_name_index."""
    idx = bind_graph.get("semantic_name_index", {})
    for name in ("nonzero", "in_range", "always_true"):
        path = f"let_decl_demo.{name}"
        assert path in idx, f"name_index missing {path}"


def test_s42_byte_equal_roundtrip(bind_graph):
    """Round-trip invariant: lift→promote→unlift yields byte-equal source.
    (Enforced at corpus level by test_roundtrip.py; verified here as a
    belt-and-suspenders check that S42 does not corrupt node payloads.)"""
    lets = _by_role(bind_graph, "let_decl")
    for n in lets:
        if n["semantic"]["path"].startswith("let_decl_demo."):
            # Semantic layer must not have touched children/tokens/text.
            sem = n.get("semantic", {})
            assert sem.get("role") == "let_decl"
            assert "path" in sem
            assert "name" in sem


# ---------------------------------------------------------------------------
# S57 — LocalVariableDeclaration (property/sequence-scope local vars)
# ---------------------------------------------------------------------------


def _local_vars_under(graph, parent_path):
    return [n for n in _by_role(graph, "local_var")
            if n["semantic"]["path"].startswith(parent_path + ".")]


def test_s57_local_var_nodes_promoted(bind_graph):
    """Each Declarator inside a LocalVariableDeclaration surfaces as a
    role=local_var node — three under the property (``hits``, ``mask``,
    ``scratch``) and one under the sequence (``seen``)."""
    prop_locals = _local_vars_under(bind_graph,
                                    "fifo_asserts.p_push_implies_not_full")
    seq_locals = _local_vars_under(bind_graph,
                                   "fifo_asserts.s_push_then_full")
    prop_names = sorted(n["semantic"]["name"] for n in prop_locals)
    seq_names = sorted(n["semantic"]["name"] for n in seq_locals)
    assert prop_names == ["hits", "mask", "scratch"], (
        f"property locals: {prop_names}")
    assert seq_names == ["seen"], f"sequence locals: {seq_names}"


def test_s57_has_local_var_edges_from_parent(bind_graph):
    """``has_local_var`` edges run from the enclosing property / sequence
    node — never directly from the module."""
    props = _by_role(bind_graph, "property")
    seqs = _by_role(bind_graph, "sequence")
    prop = next(p for p in props
                if p["semantic"]["name"] == "p_push_implies_not_full")
    seq = next(s for s in seqs
               if s["semantic"]["name"] == "s_push_then_full")
    prop_edges = [e for e in bind_graph["edges"]
                  if e["type"] == "has_local_var" and e["src"] == prop["id"]]
    seq_edges = [e for e in bind_graph["edges"]
                 if e["type"] == "has_local_var" and e["src"] == seq["id"]]
    assert len(prop_edges) == 3, (
        f"expected 3 has_local_var edges from property, got {len(prop_edges)}")
    assert len(seq_edges) == 1, (
        f"expected 1 has_local_var edge from sequence, got {len(seq_edges)}")


def test_s57_initializer_attribute(bind_graph):
    """``has_initializer`` is True for ``int hits = 0;`` / ``int seen = 0;``
    and False for the bare ``bit [7:0] mask, scratch;`` declarators."""
    locals_by_name = {
        n["semantic"]["name"]: n
        for n in _by_role(bind_graph, "local_var")
        if n["semantic"]["path"].startswith("fifo_asserts.")
    }
    assert locals_by_name["hits"]["semantic"]["attributes"]["has_initializer"] is True
    assert locals_by_name["seen"]["semantic"]["attributes"]["has_initializer"] is True
    assert locals_by_name["mask"]["semantic"]["attributes"]["has_initializer"] is False
    assert locals_by_name["scratch"]["semantic"]["attributes"]["has_initializer"] is False


def test_s57_data_type_attribute(bind_graph):
    """``data_type`` carries the structural type text of the declaration —
    ``int`` for the int locals, and a bit-vector type for ``mask``/``scratch``."""
    locals_by_name = {
        n["semantic"]["name"]: n
        for n in _by_role(bind_graph, "local_var")
        if n["semantic"]["path"].startswith("fifo_asserts.")
    }
    assert locals_by_name["hits"]["semantic"]["attributes"]["data_type"] == "int"
    assert locals_by_name["seen"]["semantic"]["attributes"]["data_type"] == "int"
    # mask / scratch share the bit-vector type; the exact tokenised form
    # depends on _type_text_of's whitespace-joining convention.
    mask_dt = locals_by_name["mask"]["semantic"]["attributes"]["data_type"]
    assert mask_dt.startswith("bit"), f"mask data_type: {mask_dt}"
    assert "[" in mask_dt and "7" in mask_dt and "0" in mask_dt
    assert (locals_by_name["scratch"]["semantic"]["attributes"]["data_type"]
            == mask_dt)


def test_s57_name_index_registers_paths(bind_graph):
    """All four local var paths are queryable via semantic_name_index."""
    idx = bind_graph.get("semantic_name_index", {})
    for path in (
        "fifo_asserts.p_push_implies_not_full.hits",
        "fifo_asserts.p_push_implies_not_full.mask",
        "fifo_asserts.p_push_implies_not_full.scratch",
        "fifo_asserts.s_push_then_full.seen",
    ):
        assert path in idx, f"name_index missing {path}"


def test_s57_fanout_emits_distinct_gids(bind_graph):
    """The ``bit [7:0] mask, scratch;`` multi-declarator form fans out to
    two distinct gids — neither alias to the same node."""
    idx = bind_graph.get("semantic_name_index", {})
    mask_id = idx["fifo_asserts.p_push_implies_not_full.mask"]
    scratch_id = idx["fifo_asserts.p_push_implies_not_full.scratch"]
    assert mask_id != scratch_id


def test_s57_byte_equal_roundtrip(bind_graph):
    """Semantic layer must not perturb structural payloads — the local_var
    promotion only writes node['semantic'] and appends edges."""
    locals_under = [n for n in _by_role(bind_graph, "local_var")
                    if n["semantic"]["path"].startswith("fifo_asserts.")]
    assert len(locals_under) == 4
    for n in locals_under:
        sem = n.get("semantic", {})
        assert sem.get("role") == "local_var"
        assert "path" in sem and "name" in sem
        attrs = sem.get("attributes", {})
        assert "data_type" in attrs and "has_initializer" in attrs
