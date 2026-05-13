"""S27 — Class constraint declarations and prototypes.

Dispatched from pass 1 of ``dispatch.promote`` (same model as S24/S25/S26:
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


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ConstraintDeclaration, _s27_constraint),
    (pyslang.SyntaxKind.ConstraintPrototype, _s27_constraint_prototype),
]
