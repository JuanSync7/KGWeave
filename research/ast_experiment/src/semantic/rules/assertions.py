"""SVA *use sites* — S16 (concurrent) + S17 (immediate) assertion statements
+ S39 (DefaultDisableDeclaration).

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

S39 promotes ``default disable iff <expr>;`` — the implicit disable
condition for all concurrent assertions in a scope. One per enclosing
module / interface / checker / program. Path key:
``<scope>.__default_disable__``. A ``has_default_disable`` edge is emitted
from the enclosing scope. Identifier tokens in the disable expression get
``reads`` edges so signal dependencies are queryable. Promotion lives in
pass 1 of ``dispatch.promote`` where ``module_stack`` is maintained.

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


def rule_s39(*args, **kwargs):
    """DefaultDisableDeclaration is promoted in pass 1 of dispatch.promote."""
    return


rule_s39.__rule_id__ = "S39"


def _s70_concurrent_assertion_member(*args, **kwargs):
    """Wrapper-only ownership marker per CLAUDE.md lesson 5.

    ``ConcurrentAssertionMember`` is the module-scope grammar wrapper
    around a ``ConcurrentAssertionStatement`` (the inner kind, registered
    by S16). Per lesson 5, registering both wrapper and inner would
    double-promote at module scope. We therefore leave the wrapper as
    CONTAINER at runtime (this stub is never invoked from dispatch) and
    use the stub only so ``build_bucket1_checklist.py`` can attribute the
    SyntaxKind to S70 via ``__rule_id__`` introspection. Runtime
    promotion fires via the inner statement kind (S16). No dispatch
    branch.
    """
    return


_s70_concurrent_assertion_member.__rule_id__ = "S70"


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
    (pyslang.SyntaxKind.DefaultDisableDeclaration, rule_s39),
    # S70: wrapper-only ownership stub (no dispatch branch — see lesson 5).
    (pyslang.SyntaxKind.ConcurrentAssertionMember, _s70_concurrent_assertion_member),
]
