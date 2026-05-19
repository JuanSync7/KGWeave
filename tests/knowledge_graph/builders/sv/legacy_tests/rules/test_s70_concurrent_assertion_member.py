"""S70: ``ConcurrentAssertionMember`` ownership-only marker.

``ConcurrentAssertionMember`` is the module-scope grammar wrapper around a
``ConcurrentAssertionStatement`` (assert/assume/cover/cover-sequence/
restrict/expect property). Per ``CLAUDE.md`` lesson 5 (wrapper-kind
dedup), only the **inner** statement kind is registered for runtime
promotion — S16 already does that. S70 exists purely as an ownership
stub so the Bucket-1 checklist marks ``ConcurrentAssertionMember`` as
``Sem ✅`` (owned by S70) without adding a dispatch branch that would
double-promote the assertion at module scope.

Tests:

* S70 is registered in ``dispatch._ACTIVE_RULE_IDS``
* The metadata stub is reachable in ``rules.assertions.RULES`` and pins
  ``__rule_id__ == "S70"`` on the ``ConcurrentAssertionMember`` kind
* Module-scope concurrent assertions still promote to **exactly one**
  semantic node each (no duplicate from a wrapper branch)
* The inner kind (e.g. ``AssertPropertyStatement``) keeps its S16 owner
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


def _assertions(graph):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == "assertion"]


def test_s70_in_active_rule_ids():
    """S70 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S70" in _ACTIVE_RULE_IDS


def test_s70_stub_owns_concurrent_assertion_member():
    """The metadata stub registered for
    ``SyntaxKind.ConcurrentAssertionMember`` must pin
    ``__rule_id__ == 'S70'``."""
    from knowledge_graph.builders.sv.semantic.rules import assertions
    matches = [
        fn for (kind, fn) in assertions.RULES
        if kind == pyslang.SyntaxKind.ConcurrentAssertionMember
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for ConcurrentAssertionMember, "
        f"got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S70"


def test_no_duplicate_node_for_module_scope_assert(bind_graph):
    """Module-scope ``a_no_push_when_full: assert property (...)`` parses
    as a ``ConcurrentAssertionMember`` wrapping the inner
    ``AssertPropertyStatement``. Per lesson 5 we must see exactly ONE
    assertion node — not two — proving S70 did not add a dispatch branch
    that double-promotes."""
    matches = [a for a in _assertions(bind_graph)
               if a["semantic"]["name"] == "a_no_push_when_full"]
    assert len(matches) == 1, (
        f"expected exactly one assertion node (no wrapper double-promote); "
        f"got {len(matches)}"
    )


def test_inner_kind_still_owned_by_s16():
    """``AssertPropertyStatement`` (the inner kind) must keep its S16
    owner — S70 only annotates the wrapper."""
    from knowledge_graph.builders.sv.semantic.rules import assertions
    matches = [
        fn for (kind, fn) in assertions.RULES
        if kind == pyslang.SyntaxKind.AssertPropertyStatement
    ]
    assert len(matches) == 1
    assert getattr(matches[0], "__rule_id__", None) == "S16"
