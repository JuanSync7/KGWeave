"""S18 — ClockingDeclaration promotion.
S40 — DefaultClockingReference edge-only promotion.

The promotion of clocking blocks lives in pass 1 of ``dispatch.promote``
(mirroring S14/S15's property/sequence handling). The metadata entry below
pins ``__rule_id__`` against ``pyslang.SyntaxKind.ClockingDeclaration`` so
the registry-derived Bucket-1 checklist counts it as PROMOTE_NOW.

The ``default``/``global`` modifier keywords are detected structurally via
the leading direct-child token kind (``DefaultKeyword`` / ``GlobalKeyword``)
of the ``ClockingDeclarationSyntax`` — no regex on source text.

S40 (DefaultClockingReference) is edge-only: ``default clocking <name>;``
has no independent identity — it is purely a pointer from the enclosing scope
to an existing clocking block. Pass 1 emits a ``default_clocking`` edge from
the enclosing module/interface/checker/program to the resolved clocking node
(``_unresolved.<name>`` fallback if not yet in name_index). The metadata stub
below carries ``__rule_id__="S40"`` as the ownership marker.

Planned future S-rule owners under this module (still stubs):

* ClockingItem
* ClockingSkew
* ClockingDirection
* DefaultSkewItem
* GlobalClockingDeclaration
"""

from __future__ import annotations

import pyslang


def _s18_clocking(*args, **kwargs):
    """ClockingDeclaration is promoted in pass 1 of dispatch.promote."""
    return


_s18_clocking.__rule_id__ = "S18"


def _s40_stub(*args, **kwargs):
    """DefaultClockingReference is edge-only; promotion handled in pass 1 of
    dispatch.promote. This stub exists solely as an ownership marker."""
    return


_s40_stub.__rule_id__ = "S40"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ClockingDeclaration, _s18_clocking),
    (pyslang.SyntaxKind.DefaultClockingReference, _s40_stub),
]
