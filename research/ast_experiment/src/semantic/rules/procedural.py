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
]
