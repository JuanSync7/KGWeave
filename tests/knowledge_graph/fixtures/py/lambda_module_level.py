"""Lambda referencing a module-level binding (v1.8-#3).

The module-level ``call_foo`` lambda references ``foo`` which is
bound at module scope. Expected resolution: ``foo`` -> ``module-level``.
"""

from __future__ import annotations


def foo(arg):
    return arg


call_foo = lambda x: foo(x)  # noqa: E731
