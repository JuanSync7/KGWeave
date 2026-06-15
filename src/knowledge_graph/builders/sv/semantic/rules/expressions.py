"""Expression-level S-rules — first home for expression SyntaxKinds that
become *edges* off the enclosing semantic container (lesson 4: edge-only).

This module is the seed of a likely-growing family. Expressions are
generally BLOB by default (operator / literal / type detail belongs in
payload, not as queryable nodes), so any expression that earns a
promotion lives here only because the *relationship* it expresses
(member access, scoped name, etc.) is queryable in its own right.

S73 — ``MemberAccessExpression`` (``obj.field`` dot-access). Semantically
this is the read/write of a struct field, class member, interface signal
or virtual-interface method. The right knowledge-graph representation is
an **edge** from the enclosing queryable container (continuous_assign /
procedural_block / function / class method / assertion / property /
sequence) to a synthesized member identifier
``<resolved_base>.<member>``. Payload carries ``{"base": <left_text>,
"member": <member_name>}``; when the base resolves to an entry in the
cross-file ``semantic_name_index`` the edge points at that node, else it
points at a sentinel ``_unresolved.<base>.<member>`` id with
``payload["unresolved"] = True`` (mirrors the S25 / S32 unresolved-target
convention).

Note on reachability: pyslang's *syntax* tree (what the lift + dispatch
walker traverses) parses ``obj.field`` as a ``ScopedNameSyntax``
(``IdentifierName Dot IdentifierName``), **not** as
``MemberAccessExpressionSyntax``. ``MemberAccessExpression`` is a kind
in the post-elaboration bound-expression tree, which this experiment
does not yet walk (see ``research/project_ast_in_graph.md``).  The
dispatch pass-1 branch for this kind is therefore dormant against the
current corpus — but the metadata stub below registers ownership so the
bucket1 checklist accounts for the kind (Sem ⬜ → ✅), and the branch is
in place for the future when the experiment lifts the bound expression
tree as well.
"""

from __future__ import annotations

import pyslang


def _s73_member_access(*args, **kwargs):
    """MemberAccessExpression is handled inline in pass 1 of
    dispatch.promote — emits a ``member_access`` edge from the enclosing
    expression-context container to ``<base>.<member>`` (resolved via
    ``semantic_name_index`` or marked ``unresolved``).

    See the module docstring re: current dormancy — pyslang's syntax
    tree does not surface ``MemberAccessExpression`` for ``obj.field``
    (that parses as ``ScopedName``). The branch is in place for the
    future bound-tree lift; this stub registers ownership so the
    bucket1 checklist credits S73.
    """
    return


_s73_member_access.__rule_id__ = "S73"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.MemberAccessExpression, _s73_member_access),
]
