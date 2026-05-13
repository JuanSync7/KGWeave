"""SVA *use sites* — S16 (concurrent) + S17 (immediate) assertion statements.

S16 promotes the six concurrent-assertion SyntaxKinds carried by
``ConcurrentAssertionStatementSyntax`` nodes. S17 promotes the three
immediate-assertion SyntaxKinds (assert / assume / cover) that live inside
procedural contexts (always / initial / final / function / task). The
actual promotion runs in pass 1 of ``dispatch.promote`` (alongside
S14/S15); the metadata entries below pin ``__rule_id__`` so the
registry-derived Bucket-1 checklist counts each SyntaxKind as PROMOTE_NOW.

A concurrent assertion at module top-level scope is parsed as a
``ConcurrentAssertionMemberSyntax`` wrapping the inner
``ConcurrentAssertionStatementSyntax``; similarly, ``ImmediateAssertionMember``
wraps the inner immediate statement when written at module scope. We
register only the **inner** kinds — the wrappers are left as CONTAINER
(they carry no identity of their own beyond the wrapped statement) —
which dedupes both forms naturally.

S17 also recognises the ``DeferredAssertion`` child node (carrying the
``#0`` delay or ``final`` keyword) attached to an immediate-assert
statement to set ``attributes["deferred"] = True`` on the promoted node.
``DeferredAssertion`` itself stays CONTAINER (it is a modifier, not a
queryable entity).

Planned future S-rule owners under this module (still stubs):

* AssertionItemPort
* AssertionItemPortList
"""

from __future__ import annotations

import pyslang


def _s16_assertion(*args, **kwargs):
    """Concurrent assertion statements are promoted in pass 1 of dispatch.promote."""
    return


_s16_assertion.__rule_id__ = "S16"


def _s17_assertion(*args, **kwargs):
    """Immediate assertion statements are promoted in pass 1 of dispatch.promote."""
    return


_s17_assertion.__rule_id__ = "S17"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.AssertPropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.AssumePropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.CoverPropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.CoverSequenceStatement, _s16_assertion),
    (pyslang.SyntaxKind.RestrictPropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.ExpectPropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.ImmediateAssertStatement, _s17_assertion),
    (pyslang.SyntaxKind.ImmediateAssumeStatement, _s17_assertion),
    (pyslang.SyntaxKind.ImmediateCoverStatement, _s17_assertion),
]
