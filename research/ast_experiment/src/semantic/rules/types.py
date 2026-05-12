"""Type rules — S9 (Package, Typedef, Enum).

The actual promotion of package/typedef/enum nodes lives in dispatch.promote's
pass 1 (declarative tree walk). The metadata entries below pin the rule_id
under each pyslang kind so the bucket1 checklist derives correctly.
"""

from __future__ import annotations

import pyslang


def _s9a_package(*args, **kwargs):
    return


def _s9b_typedef(*args, **kwargs):
    return


def _s9c_enum_type(*args, **kwargs):
    return


_s9a_package.__rule_id__ = "S9a"
_s9b_typedef.__rule_id__ = "S9b"
_s9c_enum_type.__rule_id__ = "S9c"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.PackageDeclaration, _s9a_package),
    (pyslang.SyntaxKind.TypedefDeclaration, _s9b_typedef),
    (pyslang.SyntaxKind.EnumType, _s9c_enum_type),
]
