"""S72 — ``DeferredAssertion`` wrapper / ``defer_mode`` attribute lift.

Per CLAUDE.md lesson 5 the ``DeferredAssertion`` wrapper itself stays
CONTAINER (registering it as its own promoted node would double-count
one user-level immediate assertion). The discriminating modifier ``#0``
vs ``final`` is *lifted* onto the inner ``ImmediateAssert*`` node that
S17 promotes, as ``semantic.attributes["defer_mode"]`` ("zero" or
"final"). Plain immediate asserts (no wrapper) have no ``defer_mode``
key at all (and ``deferred`` stays False).

Corpus: ``fifo_asserts.sv`` already exercises both forms inside the
``always_comb`` block — ``a_imm_deferred_zero: assert #0 (...)`` and
``a_imm_deferred_final: assert final (...)`` — plus a plain immediate
assert (``a_imm_no_push_when_full``) that must NOT have ``defer_mode``.
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


def _immediate_assertions(graph):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == "assertion"
            and n["semantic"].get("attributes", {}).get("kind", "").endswith("_immediate")]


def _by_name(graph, name):
    matches = [n for n in graph["nodes"]
               if n.get("semantic", {}).get("name") == name]
    assert len(matches) == 1, f"expected exactly one node named {name!r}, got {len(matches)}"
    return matches[0]


def test_s72_defer_mode_zero_lifted(bind_graph):
    """``assert #0 (...)`` lifts ``defer_mode='zero'`` onto the inner
    immediate-assert node (the DeferredAssertion wrapper itself stays
    CONTAINER)."""
    a = _by_name(bind_graph, "a_imm_deferred_zero")
    attrs = a["semantic"]["attributes"]
    assert attrs["kind"] == "assert_immediate"
    assert attrs["deferred"] is True
    assert attrs["defer_mode"] == "zero"


def test_s72_defer_mode_final_lifted(bind_graph):
    """``assert final (...)`` lifts ``defer_mode='final'`` onto the
    inner immediate-assert node — discriminated structurally via
    ``DeferredAssertionSyntax.finalKeyword`` (no token-text scan)."""
    a = _by_name(bind_graph, "a_imm_deferred_final")
    attrs = a["semantic"]["attributes"]
    assert attrs["kind"] == "assert_immediate"
    assert attrs["deferred"] is True
    assert attrs["defer_mode"] == "final"


def test_s72_plain_immediate_has_no_defer_mode(bind_graph):
    """A plain ``assert (...)`` (no DeferredAssertion wrapper child) has
    ``deferred=False`` and no ``defer_mode`` key — so downstream
    consumers can use ``"defer_mode" in attrs`` as the boolean check."""
    a = _by_name(bind_graph, "a_imm_no_push_when_full")
    attrs = a["semantic"]["attributes"]
    assert attrs["kind"] == "assert_immediate"
    assert attrs["deferred"] is False
    assert "defer_mode" not in attrs


def test_s72_one_promoted_node_per_assert(bind_graph):
    """Lesson 5 dedup: registering the ``DeferredAssertion`` wrapper as
    its own promoted node would double-count. Verify each labeled
    deferred assert yields exactly one assertion node."""
    for name in ("a_imm_deferred_zero", "a_imm_deferred_final"):
        matches = [n for n in _immediate_assertions(bind_graph)
                   if n["semantic"].get("name") == name]
        assert len(matches) == 1, (
            f"expected exactly one assertion node for {name!r}, "
            f"got {len(matches)} — wrapper double-promotion regression?"
        )


def test_s72_active_rule_registered():
    """S72 must be in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    counts ``DeferredAssertion`` as PROMOTE_NOW."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S72" in _ACTIVE_RULE_IDS


def test_s72_ownership_stub_attributed():
    """The ``DeferredAssertion`` SyntaxKind in the RULES table must
    carry ``__rule_id__ == 'S72'`` so the checklist builder credits the
    rule (ownership-stub pattern, like S70 / S71 / S63)."""
    from research.ast_experiment.src.semantic.rules.assertions import RULES
    matches = [(k, fn) for (k, fn) in RULES
               if k == pyslang.SyntaxKind.DeferredAssertion]
    assert len(matches) == 1
    _, fn = matches[0]
    assert getattr(fn, "__rule_id__", None) == "S72"
