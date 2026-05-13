"""S19 — ProceduralAssign / ProceduralDeassign promotion.

The promotion of procedural-continuous-assign statements lives in pass 1 of
``dispatch.promote`` (mirroring S14..S18's declarative pass-1 handling). The
metadata entries below pin ``__rule_id__`` against the two pyslang kinds so
the registry-derived Bucket-1 checklist counts them as PROMOTE_NOW.

The LHS target is extracted structurally via ``_lhs_target_name`` (the first
Identifier token under the statement, which in both grammars is the LHS) —
no regex on source text. An optional ``drives`` edge is emitted when the LHS
resolves to a known semantic node via the shared cross-file name index;
otherwise the edge is skipped silently (LHS resolution is best-effort).

Planned future S-rule owners under this module (still stubs):

* AlwaysBlock
* AlwaysLatchBlock
* InitialBlock
* FinalBlock
* ProceduralForceStatement       (S20)
* ProceduralReleaseStatement     (S20)
* EventTriggerStatement          (S21)
* BlockingEventTriggerStatement  (S21)
* NonblockingEventTriggerStatement (S21)
"""

from __future__ import annotations

import pyslang


def _s19_procedural_assign(*args, **kwargs):
    """ProceduralAssignStatement is promoted in pass 1 of dispatch.promote."""
    return


def _s19_procedural_deassign(*args, **kwargs):
    """ProceduralDeassignStatement is promoted in pass 1 of dispatch.promote."""
    return


_s19_procedural_assign.__rule_id__ = "S19"
_s19_procedural_deassign.__rule_id__ = "S19"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ProceduralAssignStatement, _s19_procedural_assign),
    (pyslang.SyntaxKind.ProceduralDeassignStatement, _s19_procedural_deassign),
]
