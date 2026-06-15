"""S83: ``ConstructorName`` ownership-only marker.

``SyntaxKind.ConstructorName`` is the ``new`` keyword token wrapped as a
name expression. pyslang reuses ``KeywordNameSyntax`` for it (the same
Python class also carries other keyword-name kinds — lesson 1 of
``CLAUDE.md`` says key on ``.kind``, never on ``_cls(node)``). Probing
``corpus/cls_corpus.sv`` shows ConstructorName arising in two places:

* As the **name** child of a ``FunctionPrototypeSyntax`` belonging to a
  ``function new(); ... endfunction`` constructor declaration inside a
  ``ClassMethodDeclarationSyntax``. The S26 branch in ``dispatch.promote``
  already detects this via ``common.tokens._is_constructor`` and lifts it
  onto the enclosing class-method node as ``kind="new"`` (see
  ``_class_method_name_and_kind``).
* As the callee inside a ``NewClassExpressionSyntax`` (``x = new();``).
  That expression is owned at the expression layer; the inner
  ``ConstructorName`` is again just the literal ``new`` token wrapped as
  a NameSyntax.

In **both** appearances the ConstructorName node carries no information
beyond "this is the ``new`` keyword in name-position" — a single-token
attribute of the surrounding construct, with no independent identity
worth its own queryable node. This is the classic attribute-only
ownership pattern used by S60 / S63 / S79 / S82.

We register an **ownership-only stub** so the Bucket-1 checklist marks
``ConstructorName`` as ``Sem ✅`` (owner S83). Runtime semantics already
exist: a class method whose ``ConstructorName`` was its prototype name
is promoted with ``kind="new"`` by S26, and ``NewClassExpression``
handling already absorbs the constructor-call form. No additional
``dispatch.py`` branch is required, mirroring the S82 contract.

Tests:

* S83 is registered in ``dispatch._ACTIVE_RULE_IDS``
* The metadata stub is reachable in ``rules.types.RULES`` and pins
  ``__rule_id__ == "S83"`` on the ``ConstructorName`` kind
* ``SyntaxKind.ConstructorName`` resolves through the rule-table
  composition (no duplicate-dispatch assertion fires)
"""

from __future__ import annotations

import pyslang


def test_s83_in_active_rule_ids():
    """S83 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S83" in _ACTIVE_RULE_IDS


def test_s83_stub_owns_constructor_name():
    """The metadata stub registered for ``SyntaxKind.ConstructorName`` must
    pin ``__rule_id__ == 'S83'``."""
    from knowledge_graph.builders.sv.semantic.rules import types
    matches = [
        fn for (kind, fn) in types.RULES
        if kind == pyslang.SyntaxKind.ConstructorName
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for ConstructorName, got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S83"


def test_s83_dispatches_through_rule_table():
    """``SyntaxKind.ConstructorName`` must resolve through the composed
    RULE_TABLE (i.e. no duplicate-dispatch assertion fires when the
    rules package is imported, and the kind maps to the S83 stub)."""
    from knowledge_graph.builders.sv.semantic.rules import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.ConstructorName)
    assert fn is not None, (
        "ConstructorName missing from RULE_TABLE — types.RULES did not "
        "register the S83 stub"
    )
    assert getattr(fn, "__rule_id__", None) == "S83"
