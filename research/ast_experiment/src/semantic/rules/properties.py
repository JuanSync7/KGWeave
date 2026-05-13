"""SVA *definitions* — S14 (PropertyDeclaration).

The promotion of property nodes lives in ``dispatch.promote``'s pass 1
(mirroring S10's function/task handling). The metadata entry below pins
``__rule_id__ = "S14"`` against ``pyslang.SyntaxKind.PropertyDeclaration``
so the registry-derived Bucket-1 checklist counts it as PROMOTE_NOW.

Planned future S-rule owners under this module (still stubs):

* SequenceDeclaration (S15)
* PropertySpec / PropertyType
* LetDeclaration
"""

from __future__ import annotations

import pyslang


def _s14_property(*args, **kwargs):
    """PropertyDeclaration is promoted in pass 1 of dispatch.promote."""
    return


_s14_property.__rule_id__ = "S14"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.PropertyDeclaration, _s14_property),
]
