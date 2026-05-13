"""S24 — ClassDeclaration promotion + S25 Extends/Implements edges.

Dispatched from pass 1 of ``dispatch.promote`` (same model as S14/S15/S18/S22:
declarations need to be visible to later passes before any rule resolves them
by hierarchical name). The metadata stub below pins ``__rule_id__`` against
``pyslang.SyntaxKind.ClassDeclaration`` so the registry-derived Bucket-1
checklist counts it as PROMOTE_NOW.

Pass 1 detects the structural modifiers ``virtual`` / ``interface`` / ``final``
and ``#(params)`` parameterization by walking the ClassDeclarationSyntax's
direct Token / SyntaxNode children — no regex on source text. The class body
(members, methods, properties, extends/implements clauses) stays BLOB at
S24; S25 and S26 will promote those sub-elements via the ``class_stack``
maintained alongside ``module_stack`` and ``covergroup_stack``.

S25 (ExtendsClause / ImplementsClause) is also handled inline in the same
pass-1 branch — the clauses are direct children of the ClassDeclarationSyntax
and the class's ``gid`` is already in hand, so there's no benefit to walking
the clause as a separate dispatched rule (and doing so would require a
parent-up rewalk via ``class_stack``). The metadata stubs below pin
``__rule_id__="S25"`` against those two SyntaxKinds so the registry-derived
Bucket-1 checklist flips them from "future PROMOTE" to "promoted by S25".

Planned future S-rule owners under this module (still stubs):

* ClassMethodDeclaration   (S26)
* ClassPropertyDeclaration (S26)
"""

from __future__ import annotations

import pyslang


def _s24_class(*args, **kwargs):
    """ClassDeclaration is promoted in pass 1 of dispatch.promote."""
    return


_s24_class.__rule_id__ = "S24"


def _s25_extends(*args, **kwargs):
    """ExtendsClause is handled inline in pass 1 of dispatch.promote — see
    the ClassDeclarationSyntax branch. This stub exists only to register
    the SyntaxKind under an active ``__rule_id__`` for the Bucket-1
    checklist."""
    return


_s25_extends.__rule_id__ = "S25"


def _s25_implements(*args, **kwargs):
    """ImplementsClause is handled inline in pass 1 of dispatch.promote —
    see the ClassDeclarationSyntax branch. This stub exists only to
    register the SyntaxKind under an active ``__rule_id__`` for the
    Bucket-1 checklist."""
    return


_s25_implements.__rule_id__ = "S25"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ClassDeclaration, _s24_class),
    (pyslang.SyntaxKind.ExtendsClause, _s25_extends),
    (pyslang.SyntaxKind.ImplementsClause, _s25_implements),
]
