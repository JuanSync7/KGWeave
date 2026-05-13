"""SVA *use sites* — S16 (concurrent assertion statements).

S16 promotes the six concurrent-assertion SyntaxKinds carried by
``ConcurrentAssertionStatementSyntax`` nodes to ``role="assertion"``
queryable nodes. The actual promotion runs in pass 1 of
``dispatch.promote`` (alongside S14/S15); the metadata entries below pin
``__rule_id__`` so the registry-derived Bucket-1 checklist counts each
SyntaxKind as PROMOTE_NOW.

A concurrent assertion at module top-level scope is parsed as a
``ConcurrentAssertionMemberSyntax`` wrapping the inner
``ConcurrentAssertionStatementSyntax``; inside a procedural block the
inner statement appears directly. We register only the **inner** kinds —
the wrapper is left as a CONTAINER (it carries no identity of its own
beyond the wrapped statement) — which dedupes both forms naturally.

Planned future S-rule owners under this module (still stubs):

* ImmediateAssertStatement
* ImmediateAssumeStatement
* ImmediateCoverStatement
* ImmediateAssertionMember
* DeferredAssertion
* AssertionItemPort
* AssertionItemPortList
"""

from __future__ import annotations

import pyslang


def _s16_assertion(*args, **kwargs):
    """Concurrent assertion statements are promoted in pass 1 of dispatch.promote."""
    return


_s16_assertion.__rule_id__ = "S16"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.AssertPropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.AssumePropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.CoverPropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.CoverSequenceStatement, _s16_assertion),
    (pyslang.SyntaxKind.RestrictPropertyStatement, _s16_assertion),
    (pyslang.SyntaxKind.ExpectPropertyStatement, _s16_assertion),
]
