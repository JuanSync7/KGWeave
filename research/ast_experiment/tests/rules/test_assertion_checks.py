"""Partial-promotion fix: an assertion gets `checks` edges to the signals it
constrains.

Before this, a node like ``a_no_push_when_full: assert property (...)`` promoted
to role="assertion" with only a ``has_assertion`` edge from its module and ZERO
edges into its property expression — "which assertions touch `full`?" needed the
structural blob / grep. This increment lifts the identifier references in the
assertion body to ``checks`` edges (assertion → signal), so the dependency is a
typed one-hop in both directions.

Design notes (verified against the structural subtree):
  * Only role="assertion" nodes are walked (S16 concurrent / S17 immediate use
    sites). The parameterised ``property`` / ``sequence`` *declarations* — whose
    bodies reference their own item-ports (``sig``/``n``/``a``/``b``) — are NOT
    assertions and are correctly untouched.
  * The assertion's own label (``NamedLabelSyntax``) and the sampling-clock
    event (``EventControl*`` subtree, e.g. ``@(posedge clk)``) are excluded: a
    ``checks`` edge means "this assertion constrains this data signal", not
    "this assertion is clocked by clk" (that is the ``sensitive_to`` relation).
  * Resolve-or-skip, mirroring S39's disable-expression ``reads``: identifiers
    that don't bind to a node (system funcs, keywords) emit no edge — no
    ``_unresolved`` noise, since not every identifier in a property is a signal.
"""

from __future__ import annotations

from pathlib import Path

from research.ast_experiment.src.build import build_kg
from research.ast_experiment.src.semantic import find_by_name, neighbors

CORPUS = sorted((Path(__file__).resolve().parents[1].parent / "corpus").glob("*.sv"))


def _checks_names(graph, assertion_path):
    a = find_by_name(graph, assertion_path)
    return {t["semantic"].get("name")
            for t in neighbors(graph, a["id"], edge_type="checks")}


def test_concurrent_assertion_checks_its_signals():
    # a_no_push_when_full: assert property (@(posedge clk) full |-> !push);
    graph, _, _ = build_kg(CORPUS)
    assert _checks_names(graph, "fifo_asserts.a_no_push_when_full") == {"full", "push"}


def test_immediate_assertion_checks_its_signals():
    # a_imm_modscope: assert (!(push && full));
    graph, _, _ = build_kg(CORPUS)
    assert _checks_names(graph, "fifo_asserts.a_imm_modscope") == {"push", "full"}


def test_sampling_clock_excluded_from_checks():
    """`clk` is the sampling clock (sensitive_to), not a checked data signal."""
    graph, _, _ = build_kg(CORPUS)
    assert "clk" not in _checks_names(graph, "fifo_asserts.a_no_push_when_full")


def test_assertion_does_not_check_itself_via_its_label():
    graph, _, _ = build_kg(CORPUS)
    a = find_by_name(graph, "fifo_asserts.a_no_push_when_full")
    targets = {t["id"] for t in neighbors(graph, a["id"], edge_type="checks")}
    assert a["id"] not in targets


def test_which_assertions_touch_full_via_walk():
    """Reverse hop: from the signal, follow `checks` IN, keep role=assertion."""
    graph, _, _ = build_kg(CORPUS)
    full = find_by_name(graph, "fifo_asserts.full")
    res = {
        n["semantic"]["name"]
        for n in neighbors(graph, full["id"], edge_type="checks", direction="in")
        if n.get("semantic", {}).get("role") == "assertion"
    }
    # a_no_push_when_full constrains `full`; c_push_event (cover push) does not.
    assert "a_no_push_when_full" in res
    assert "c_push_event" not in res
