"""S22 — CovergroupDeclaration promotion.

The promotion of covergroup blocks lives in pass 1 of ``dispatch.promote``
(mirroring S14/S15/S18's property/sequence/clocking handling). The metadata
entry below pins ``__rule_id__`` against
``pyslang.SyntaxKind.CovergroupDeclaration`` so the registry-derived
Bucket-1 checklist counts it as PROMOTE_NOW.

The clocking-event clause (``@(posedge clk)``) is detected structurally by
walking direct children of the ``CovergroupDeclarationSyntax`` for an
``EventControl*Syntax`` node — no regex on source text. The attribute is a
boolean flag only; the event details remain in the BLOB form (or under S23
when Coverpoint/CoverCross are promoted).

Planned future S-rule owners under this module (still stubs):

* Coverpoint
* CoverCross
* CoverageBins
"""

from __future__ import annotations

import pyslang


def _s22_covergroup(*args, **kwargs):
    """CovergroupDeclaration is promoted in pass 1 of dispatch.promote."""
    return


_s22_covergroup.__rule_id__ = "S22"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.CovergroupDeclaration, _s22_covergroup),
]
