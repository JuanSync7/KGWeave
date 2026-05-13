"""SVA *definitions* — S14 (PropertyDeclaration), S15 (SequenceDeclaration).

The promotion of property and sequence nodes lives in ``dispatch.promote``'s
pass 1 (mirroring S10's function/task handling). The metadata entries below
pin ``__rule_id__`` against the corresponding ``pyslang.SyntaxKind`` so the
registry-derived Bucket-1 checklist counts them as PROMOTE_NOW.

Planned future S-rule owners under this module (still stubs):

* PropertySpec / PropertyType
* LetDeclaration
"""

from __future__ import annotations

import pyslang


def _s14_property(*args, **kwargs):
    """PropertyDeclaration is promoted in pass 1 of dispatch.promote."""
    return


_s14_property.__rule_id__ = "S14"


def _s15_sequence(*args, **kwargs):
    """SequenceDeclaration is promoted in pass 1 of dispatch.promote."""
    return


_s15_sequence.__rule_id__ = "S15"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.PropertyDeclaration, _s14_property),
    (pyslang.SyntaxKind.SequenceDeclaration, _s15_sequence),
]
