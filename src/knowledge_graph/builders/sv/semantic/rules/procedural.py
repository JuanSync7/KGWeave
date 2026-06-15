"""S19 / S20 — Procedural continuous-drive statement promotion.

The promotion of procedural-continuous-drive statements lives in pass 1 of
``dispatch.promote`` (mirroring S14..S18's declarative pass-1 handling). The
metadata entries below pin ``__rule_id__`` against the four pyslang kinds so
the registry-derived Bucket-1 checklist counts them as PROMOTE_NOW.

S19 covers ``assign lhs = rhs;`` / ``deassign lhs;`` — procedural-continuous
assigns (distinct from S2's module-level continuous assigns).

S20 covers ``force lhs = rhs;`` / ``release lhs;`` — stronger variants that
override even continuous drivers (commonly used in testbenches).

S21 covers ``-> ev;`` (blocking) and ``->> ev;`` (nonblocking) named event
trigger statements. pyslang surfaces both as ``EventTriggerStatementSyntax``
— discriminated only by ``SyntaxKind`` (BlockingEventTriggerStatement vs
NonblockingEventTriggerStatement).

pyslang surfaces these families with shared syntax classes, discriminated
only by ``SyntaxKind``:

  class ProceduralAssignStatementSyntax   → kinds {ProceduralAssignStatement,
                                                   ProceduralForceStatement}
  class ProceduralDeassignStatementSyntax → kinds {ProceduralDeassignStatement,
                                                   ProceduralReleaseStatement}
  class EventTriggerStatementSyntax       → kinds {BlockingEventTriggerStatement,
                                                   NonblockingEventTriggerStatement}

The dispatch pass-1 branch keys on ``_cls(node)`` to enter the branch, then
discriminates by ``node.kind`` to pick the role label, path prefix, edge
type, and per-module counter.

The LHS target is extracted structurally via ``_lhs_target_name`` (the first
Identifier token under the statement, which in all four grammars is the LHS)
— no regex on source text. An optional ``drives`` edge is emitted when the
LHS resolves to a known semantic node via the shared cross-file name index;
otherwise the edge is skipped silently (LHS resolution is best-effort).

Planned future S-rule owners under this module (still stubs):

* AlwaysBlock
* AlwaysLatchBlock
* InitialBlock
* FinalBlock
"""

from __future__ import annotations

import pyslang


def _s19_procedural_assign(*args, **kwargs):
    """ProceduralAssignStatement is promoted in pass 1 of dispatch.promote."""
    return


def _s19_procedural_deassign(*args, **kwargs):
    """ProceduralDeassignStatement is promoted in pass 1 of dispatch.promote."""
    return


def _s20_procedural_force(*args, **kwargs):
    """ProceduralForceStatement is promoted in pass 1 of dispatch.promote."""
    return


def _s20_procedural_release(*args, **kwargs):
    """ProceduralReleaseStatement is promoted in pass 1 of dispatch.promote."""
    return


def _s21_blocking_event_trigger(*args, **kwargs):
    """BlockingEventTriggerStatement is promoted in pass 1 of dispatch.promote."""
    return


def _s21_nonblocking_event_trigger(*args, **kwargs):
    """NonblockingEventTriggerStatement is promoted in pass 1 of dispatch.promote."""
    return


_s19_procedural_assign.__rule_id__ = "S19"
_s19_procedural_deassign.__rule_id__ = "S19"
_s20_procedural_force.__rule_id__ = "S20"
_s20_procedural_release.__rule_id__ = "S20"
_s21_blocking_event_trigger.__rule_id__ = "S21"
_s21_nonblocking_event_trigger.__rule_id__ = "S21"


def rule_s42(*args, **kwargs):
    """LetDeclaration is promoted in pass 1 of dispatch.promote."""
    return


rule_s42.__rule_id__ = "S42"


def rule_s57(*args, **kwargs):
    """LocalVariableDeclaration is promoted in pass 1 of dispatch.promote.

    Each ``Declarator`` child of a ``LocalVariableDeclarationSyntax`` (the
    SVA-scope local variable form that lives inside ``sequence`` /
    ``property`` declaration bodies) surfaces as a role=local_var node with
    attrs ``{data_type, has_initializer}`` and a ``has_local_var`` edge from
    the enclosing sequence / property. Multi-declarator forms (``int a, b;``)
    fan out: the canonical syntax node carries the first name, and synthetic
    sibling nodes (S38-style) carry the rest. The actual implementation
    lives in dispatch.py pass-1 — this stub is the bucket1 ownership marker.
    """
    return


rule_s57.__rule_id__ = "S57"


def rule_s74(*args, **kwargs):
    """FunctionPort is promoted in pass 1 of dispatch.promote.

    A ``FunctionPortSyntax`` is one argument inside a function / task /
    method signature (``function int add(input int a, output int b);``).
    Each port surfaces as a queryable ``role="function_port"`` node with
    attrs ``{direction, data_type, name}`` attached to the enclosing
    function / method via a ``has_function_port`` edge.

    Parent resolution rides on a new ``function_stack`` (lesson 2:
    standard variant — child kinds of a function / method are
    semantically distinct from module members), pushed when dispatch
    enters a FunctionDeclaration / ClassMethodDeclaration /
    ClassMethodPrototype / extern-FunctionPrototype that successfully
    promotes its enclosing scope. The frame carries
    ``(parent_gid, parent_path)``; a sentinel ``(None, "")`` frame is
    pushed on un-promoted scopes so pop-on-subtree-exit stays symmetric.

    Path keys are ``<scope>.<function>.<port_name>`` and are *not*
    registered in ``name_index`` (port names collide across functions
    — ``add.a`` and ``sub.a`` are distinct ports, name-indexing would
    overwrite). Cross-port references resolve via traversal.
    """
    return


rule_s74.__rule_id__ = "S74"


def _s75_stub(*args, **kwargs):
    """FunctionPortList — wrapper ownership marker only.

    ``FunctionPortListSyntax`` is the parenthesised wrapper containing
    one or more ``FunctionPortSyntax`` entries inside a function / task /
    method signature (``function int add(input int a, output int b);`` —
    the ``(input int a, output int b)`` is the FunctionPortList).

    Per ``CLAUDE.md`` lesson 5 (wrapper-kind dedup), the wrapper carries
    no independent identity — its only role is to group the inner
    ``FunctionPort`` children. We therefore leave it as CONTAINER for
    structural traversal and only register an ownership stub here so the
    Bucket-1 checklist regenerator attributes ``FunctionPortList`` to
    S75 via ``__rule_id__`` introspection. Runtime promotion fires per
    child via the inner ``FunctionPort`` kind (S74). No dispatch branch.
    """
    return


_s75_stub.__rule_id__ = "S75"


def _s76_stub(*args, **kwargs):
    """DefaultFunctionPort — ownership-only marker (no dispatch branch).

    ``DefaultFunctionPortSyntax`` represents the bare ``default`` keyword
    that pyslang's grammar allows in a ``FunctionPortListSyntax`` (e.g.
    ``(default)`` or ``(input int a, default)``). The kind is reserved in
    pyslang's SyntaxKind enum, but the parser raises
    ``DiagCode.DefaultArgNotAllowed`` for every instance — no valid
    SystemVerilog program ever yields a ``DefaultFunctionPort``.

    All KGWeave corpus files are required to round-trip with zero
    diagnostics, so the kind is unreachable at runtime. Per ``CLAUDE.md``
    lesson 4 / lesson 5 (kind with no clean-SV instantiation gets an
    ownership-only stub rather than a dispatch branch), S76 ships as:

      * metadata entry ``(SyntaxKind.DefaultFunctionPort, _s76_stub)``
        carrying ``__rule_id__='S76'`` here in RULES
      * ``"S76"`` added to ``dispatch._ACTIVE_RULE_IDS`` so the bucket1
        checklist regenerator attributes the kind to S76
      * NO dispatch branch — adding one would be dead code under the
        zero-diagnostic invariant

    Sibling rule S74 (FunctionPort) and S75 (FunctionPortList wrapper)
    cover the reachable function-port surface. If a future corpus
    addition ever produces a ``DefaultFunctionPort`` (it would have to
    explicitly accept the ``DefaultArgNotAllowed`` diagnostic), promote
    this stub to a real dispatch branch with the ``function_stack``
    parent-resolution scheme from S74 — the role would still be
    ``function_port`` (the ``default`` keyword is itself the lexical
    "name") with ``direction=data_type=None`` to stay honest about the
    absent declarator.
    """
    return


_s76_stub.__rule_id__ = "S76"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ProceduralAssignStatement, _s19_procedural_assign),
    (pyslang.SyntaxKind.ProceduralDeassignStatement, _s19_procedural_deassign),
    (pyslang.SyntaxKind.ProceduralForceStatement, _s20_procedural_force),
    (pyslang.SyntaxKind.ProceduralReleaseStatement, _s20_procedural_release),
    (pyslang.SyntaxKind.BlockingEventTriggerStatement,
     _s21_blocking_event_trigger),
    (pyslang.SyntaxKind.NonblockingEventTriggerStatement,
     _s21_nonblocking_event_trigger),
    (pyslang.SyntaxKind.LetDeclaration, rule_s42),
    (pyslang.SyntaxKind.LocalVariableDeclaration, rule_s57),
    (pyslang.SyntaxKind.FunctionPort, rule_s74),
    # S75: Wrapper ownership marker per lesson 5; child FunctionPorts
    # promote via S74. No dispatch branch.
    (pyslang.SyntaxKind.FunctionPortList, _s75_stub),
    # S76: Ownership marker for DefaultFunctionPort. pyslang reserves the
    # kind but flags every instance with DefaultArgNotAllowed; the kind is
    # unreachable in clean-SV corpora and ships as a stub only (lesson 4 /
    # lesson 5). No dispatch branch.
    (pyslang.SyntaxKind.DefaultFunctionPort, _s76_stub),
]
