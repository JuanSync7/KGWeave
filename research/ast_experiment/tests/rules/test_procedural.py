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
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

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
