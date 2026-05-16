"""S82: ``ClassSpecifier`` ownership-only marker.

``ClassSpecifierSyntax`` is the SystemVerilog-2023 method override
specifier — the ``: initial`` / ``: extends`` / ``: final`` qualifier
that appears between the ``function`` / ``task`` keyword and the return
type on a class method prototype::

    class C;
      function : initial void f();
      endfunction
    endclass

Probe summary (run against pyslang's default LRM-2017 parser none of the
override-specifier syntactic placements parse; only the SV-2023 parser
emits ``SyntaxKind.ClassSpecifier``). The node carries two tokens only:

* ``keyword`` — one of ``initial`` / ``extends`` / ``final``
* ``colon``  — the ``:`` punctuator

Its parent in the syntax tree is the enclosing ``FunctionPrototype``.
The override specifier is a single-keyword attribute of the method
prototype; it has no independent identity worth promoting as its own
queryable node.

Per ``CLAUDE.md`` lesson 4 (edge-only / attribute-only kinds), and
because the live corpus is parsed with the default SV-2017 settings
(``research/ast_experiment/src/build.py`` calls
``pyslang.SyntaxTree.fromText`` without a SV-2023 ``ParserOptions``),
``ClassSpecifier`` will never appear in any real graph. We register an
**ownership-only stub** so the Bucket-1 checklist flips its row to
``Sem ✅`` (owner S82) — exactly the pattern used by S60 / S63 / S79.
If a future iteration switches the parser to SV-2023, runtime
attribute-lifting onto the parent ``FunctionPrototype`` semantic node
can be added without breaking this contract.

Tests:

* S82 is registered in ``dispatch._ACTIVE_RULE_IDS``
* The metadata stub is reachable in ``rules.types.RULES`` and pins
  ``__rule_id__ == "S82"`` on the ``ClassSpecifier`` kind
* ``SyntaxKind.ClassSpecifier`` resolves through the rule-table
  composition (no duplicate-dispatch assertion fires)
"""

from __future__ import annotations

import pyslang


def test_s82_in_active_rule_ids():
    """S82 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S82" in _ACTIVE_RULE_IDS


def test_s82_stub_owns_class_specifier():
    """The metadata stub registered for ``SyntaxKind.ClassSpecifier`` must
    pin ``__rule_id__ == 'S82'``."""
    from research.ast_experiment.src.semantic.rules import types
    matches = [
        fn for (kind, fn) in types.RULES
        if kind == pyslang.SyntaxKind.ClassSpecifier
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for ClassSpecifier, got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S82"


def test_s82_dispatches_through_rule_table():
    """``SyntaxKind.ClassSpecifier`` must resolve through the composed
    RULE_TABLE (i.e. no duplicate-dispatch assertion fires when the
    rules package is imported, and the kind maps to the S82 stub)."""
    from research.ast_experiment.src.semantic.rules import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.ClassSpecifier)
    assert fn is not None, (
        "ClassSpecifier missing from RULE_TABLE — types.RULES did not "
        "register the S82 stub"
    )
    assert getattr(fn, "__rule_id__", None) == "S82"
