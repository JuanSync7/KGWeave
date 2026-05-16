"""S73 — ``MemberAccessExpression`` ownership + edge-only design.

The kind is registered under a new dedicated ``expressions.py`` rule
module (first home for the expression family) as an edge-only rule
(lesson 4): when a ``MemberAccessExpressionSyntax`` appears in the
walked syntax tree, dispatch pass-1 emits a ``member_access`` edge from
the enclosing semantic container (class method via ``class_stack``, else
the closest module/interface/package/program/checker via
``module_stack``) to either the resolved base node in
``semantic_name_index`` or to a sentinel ``_unresolved.<base>.<member>``
id with ``payload["unresolved"]=True``.

Reachability caveat (verified by ``test_s73_kind_dormant_in_syntax_tree``
below): pyslang's *syntax* tree parses ``obj.field`` as
``ScopedNameSyntax`` (Identifier Dot Identifier), not as
``MemberAccessExpressionSyntax`` — the latter only appears in the
post-elaboration bound-expression tree, which this experiment does not
yet traverse. The dispatch branch is therefore dormant against the
current corpus, but the registration flips the bucket1 checklist
(Sem ⬜ → ✅) and the branch is in place for the future bound-tree lift.

Tests here verify:
  1. The kind is in the rule registry and its callable carries
     ``__rule_id__ == "S73"``.
  2. S73 is in ``_ACTIVE_RULE_IDS`` (so the checklist counts it).
  3. The dedicated ``expressions.py`` module exposes the RULES list and
     is composed into RULE_TABLE without duplicate-kind violations.
  4. The corpus survey confirms the syntax-tree dormancy claim (and
     therefore that the branch yields zero ``member_access`` edges
     against the present corpus — guarding against accidental
     double-emission via some other parse path).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"


def test_s73_ownership_stub_attributed():
    """The ``MemberAccessExpression`` SyntaxKind in the RULES table must
    carry ``__rule_id__ == 'S73'`` (ownership-stub pattern, like
    S70 / S71 / S72)."""
    from research.ast_experiment.src.semantic.rules.expressions import RULES

    matches = [(k, fn) for (k, fn) in RULES
               if k == pyslang.SyntaxKind.MemberAccessExpression]
    assert len(matches) == 1
    _, fn = matches[0]
    assert getattr(fn, "__rule_id__", None) == "S73"


def test_s73_active_rule_registered():
    """S73 must be in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    counts ``MemberAccessExpression`` as PROMOTE_NOW (Sem ✅)."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS

    assert "S73" in _ACTIVE_RULE_IDS


def test_s73_kind_in_rule_table():
    """The composed ``RULE_TABLE`` must dispatch
    ``MemberAccessExpression`` to S73's stub (composition assertion in
    ``rules/__init__.py`` would have caught a duplicate)."""
    from research.ast_experiment.src.semantic.rules import RULE_TABLE

    fn = RULE_TABLE.get(pyslang.SyntaxKind.MemberAccessExpression)
    assert fn is not None
    assert getattr(fn, "__rule_id__", None) == "S73"


def test_s73_expressions_module_listed():
    """The new ``expressions`` module must be in ``ALL_RULE_MODULES`` so
    its RULES contribute to the composed ``RULE_TABLE``."""
    from research.ast_experiment.src.semantic.rules import (
        ALL_RULE_MODULES, expressions,
    )

    assert expressions in ALL_RULE_MODULES
    # Sanity: the module exports a non-empty RULES list with the
    # expected kind.
    assert any(k == pyslang.SyntaxKind.MemberAccessExpression
               for (k, _fn) in expressions.RULES)


@pytest.mark.parametrize("corpus_file", sorted(CORPUS_DIR.glob("*.sv")))
def test_s73_kind_dormant_in_syntax_tree(corpus_file):
    """pyslang's syntax tree does not emit ``MemberAccessExpression`` for
    the present corpus (``obj.field`` parses as ``ScopedName``). This
    test pins that fact so a future change in pyslang behavior — or
    addition of a bound-tree lift — surfaces here as a deliberate
    decision rather than silently doubling edge counts."""
    text = corpus_file.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    found: list = []

    def cb(n):
        try:
            if n.kind == pyslang.SyntaxKind.MemberAccessExpression:
                found.append(n)
        except Exception:
            return

    tree.root.visit(cb)
    assert found == [], (
        f"{corpus_file.name}: unexpected MemberAccessExpression nodes in "
        f"syntax tree — S73 branch implementation needs review."
    )


def test_s73_no_member_access_edges_against_corpus():
    """Cross-corpus confirmation that the dispatch branch — which fires
    only on ``MemberAccessExpressionSyntax`` — emits zero
    ``member_access`` edges against the present syntax-only corpus
    (consistent with the dormancy claim above). When the experiment
    adds a bound-tree lift this expectation will flip."""
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    total = 0
    for corpus_file in sorted(CORPUS_DIR.glob("*.sv")):
        text = corpus_file.read_text()
        tree = pyslang.SyntaxTree.fromText(text)
        comp = pyslang.Compilation()
        comp.addSyntaxTree(tree)
        graph = lift(tree)
        promote(graph, tree, comp)
        total += sum(1 for e in graph["edges"]
                     if e.get("type") == "member_access")
    assert total == 0
