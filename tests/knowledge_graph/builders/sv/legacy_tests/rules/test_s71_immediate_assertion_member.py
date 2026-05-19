"""S71: ``ImmediateAssertionMember`` ownership-only marker.

``ImmediateAssertionMember`` is the module-scope grammar wrapper around
an ``ImmediateAssertionStatement`` (immediate assert / assume / cover).
Per ``CLAUDE.md`` lesson 5 (wrapper-kind dedup), only the **inner**
statement kind is registered for runtime promotion — S17 already does
that. S71 exists purely as an ownership stub so the Bucket-1 checklist
marks ``ImmediateAssertionMember`` as ``Sem ✅`` (owned by S71) without
adding a dispatch branch that would double-promote the assertion at
module scope.

Tests:

* S71 is registered in ``dispatch._ACTIVE_RULE_IDS``
* The metadata stub is reachable in ``rules.assertions.RULES`` and pins
  ``__rule_id__ == "S71"`` on the ``ImmediateAssertionMember`` kind
* A module-scope immediate ``assert (...)`` still promotes to **exactly
  one** semantic node (no duplicate from a wrapper branch)
* The inner kind (``ImmediateAssertStatement``) keeps its S17 owner
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


def _assertions(graph):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == "assertion"]


def test_s71_in_active_rule_ids():
    """S71 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S71" in _ACTIVE_RULE_IDS


def test_s71_stub_owns_immediate_assertion_member():
    """The metadata stub registered for
    ``SyntaxKind.ImmediateAssertionMember`` must pin
    ``__rule_id__ == 'S71'``."""
    from research.ast_experiment.src.semantic.rules import assertions
    matches = [
        fn for (kind, fn) in assertions.RULES
        if kind == pyslang.SyntaxKind.ImmediateAssertionMember
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for ImmediateAssertionMember, "
        f"got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S71"


def test_no_duplicate_node_for_module_scope_immediate_assert(bind_graph):
    """Module-scope ``a_imm_modscope: assert (...)`` parses as an
    ``ImmediateAssertionMember`` wrapping the inner
    ``ImmediateAssertStatement``. Per lesson 5 we must see exactly ONE
    assertion node — not two — proving S71 did not add a dispatch branch
    that double-promotes."""
    matches = [a for a in _assertions(bind_graph)
               if a["semantic"]["name"] == "a_imm_modscope"]
    assert len(matches) == 1, (
        f"expected exactly one assertion node (no wrapper double-promote); "
        f"got {len(matches)}"
    )


def test_inner_kind_still_owned_by_s17():
    """``ImmediateAssertStatement`` (the inner kind) must keep its S17
    owner — S71 only annotates the wrapper."""
    from research.ast_experiment.src.semantic.rules import assertions
    matches = [
        fn for (kind, fn) in assertions.RULES
        if kind == pyslang.SyntaxKind.ImmediateAssertStatement
    ]
    assert len(matches) == 1
    assert getattr(matches[0], "__rule_id__", None) == "S17"
