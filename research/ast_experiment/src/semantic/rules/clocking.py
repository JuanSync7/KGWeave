"""S18 — ClockingDeclaration promotion.

The promotion of clocking blocks lives in pass 1 of ``dispatch.promote``
(mirroring S14/S15's property/sequence handling). The metadata entry below
pins ``__rule_id__`` against ``pyslang.SyntaxKind.ClockingDeclaration`` so
the registry-derived Bucket-1 checklist counts it as PROMOTE_NOW.

The ``default``/``global`` modifier keywords are detected structurally via
the leading direct-child token kind (``DefaultKeyword`` / ``GlobalKeyword``)
of the ``ClockingDeclarationSyntax`` — no regex on source text.

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


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ClockingDeclaration, _s18_clocking),
]
