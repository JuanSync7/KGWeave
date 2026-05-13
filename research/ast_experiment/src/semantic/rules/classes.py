"""S24 — ClassDeclaration promotion.

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

Planned future S-rule owners under this module (still stubs):

* ClassMethodDeclaration   (S26)
* ClassPropertyDeclaration (S26)
* ExtendsClause            (S25)
* ImplementsClause         (S25)
"""

from __future__ import annotations

import pyslang


def _s24_class(*args, **kwargs):
    """ClassDeclaration is promoted in pass 1 of dispatch.promote."""
    return


_s24_class.__rule_id__ = "S24"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ClassDeclaration, _s24_class),
]
