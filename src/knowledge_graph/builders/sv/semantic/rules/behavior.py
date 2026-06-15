"""Behavioural rules — S10 (Function, Task declarations).

The promotion of function/task nodes lives in dispatch.promote's pass 1.
The metadata entries below pin the rule_id under each pyslang kind.
"""

from __future__ import annotations

import pyslang


def _s10_function(*args, **kwargs):
    return


def _s10_task(*args, **kwargs):
    return


_s10_function.__rule_id__ = "S10"
_s10_task.__rule_id__ = "S10"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.FunctionDeclaration, _s10_function),
    (pyslang.SyntaxKind.TaskDeclaration, _s10_task),
]
