"""S27 — Class constraint declarations and prototypes.
S52 — Inline ``randomize() with { ... }`` constraint blocks.

S27 dispatched from pass 1 of ``dispatch.promote`` (same model as S24/S25/S26:
declarations need to be visible to later passes before any rule resolves them
by hierarchical name). The metadata stubs below pin ``__rule_id__="S27"``
against ``pyslang.SyntaxKind.ConstraintDeclaration`` and
``ConstraintPrototype`` so the registry-derived Bucket-1 checklist counts
them as PROMOTE_NOW.

Pass 1 detects the structural qualifier tokens ``static`` / ``pure`` /
``extern`` by walking the constraint declaration's TokenList direct child
(``_qualifier_tokens_of``). The constraint body — the ``{ ... }``
ConstraintBlock and every expression / implication / solve-before / dist
constraint nested inside — stays BLOB at S27. Only the declaration-level
node is promoted, with role=constraint and path
``<class_path>.<constraint_name>``.

S52: ``ConstraintBlock`` appears in two structural positions in pyslang:
  1. As the body child of ``ConstraintDeclaration`` / ``ConstraintPrototype``
     (already covered by S27 — the block stays BLOB there; only the
     declaration-level parent is promoted, per lesson 5 of CLAUDE.md).
  2. Directly inside ``ArrayOrRandomizeMethodExpression`` as the ``with { ... }``
     inline argument to ``obj.randomize() with { a < b; };`` (SV §18.12).
     This form has no named declaration wrapper and IS independently queryable.

S52 covers only form 2.  Detection: ``node.parent`` class is
``ArrayOrRandomizeMethodExpressionSyntax``.  Promotion: role=
``inline_constraint_block``, synthetic path
``<scope>.__inline_constraint_<byte_offset>__``, edge ``has_inline_constraint``
from the enclosing module scope.
"""

from __future__ import annotations

import pyslang


def _s27_constraint(*args, **kwargs):
    """ConstraintDeclaration is promoted in pass 1 of dispatch.promote — see
    the S27 branch. This stub exists only to register the SyntaxKind under an
    active ``__rule_id__`` for the Bucket-1 checklist."""
    return


_s27_constraint.__rule_id__ = "S27"


def _s27_constraint_prototype(*args, **kwargs):
    """ConstraintPrototype is promoted in pass 1 of dispatch.promote — see
    the S27 branch."""
    return


_s27_constraint_prototype.__rule_id__ = "S27"


def _s52_inline_constraint_block(*args, **kwargs):
    """ConstraintBlock (inline randomize() with form) is promoted in pass 1 of
    dispatch.promote — see the S52 branch.  Only ConstraintBlock nodes whose
    ``.parent`` class is ``ArrayOrRandomizeMethodExpressionSyntax`` are
    promoted; the ConstraintBlock that is the body of a ConstraintDeclaration
    stays BLOB (lesson 5: register only the innermost independently-queryable
    kind, not the wrapper-owned inner block)."""
    return


_s52_inline_constraint_block.__rule_id__ = "S52"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ConstraintDeclaration, _s27_constraint),
    (pyslang.SyntaxKind.ConstraintPrototype, _s27_constraint_prototype),
    (pyslang.SyntaxKind.ConstraintBlock, _s52_inline_constraint_block),
]
