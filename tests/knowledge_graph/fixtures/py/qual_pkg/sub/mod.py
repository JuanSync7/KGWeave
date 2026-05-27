"""Leaf module for v1.11-#1 qualname fixture.

Walker should report ``PyModule.name == 'qual_pkg.sub.mod'``. The
top-level ``foo`` binding doubles as the v1.11-#3 multi-segment
relative-import resolution target.
"""

from __future__ import annotations


def foo(x):
    return x
