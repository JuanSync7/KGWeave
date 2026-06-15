"""Lambda closure-over-outer-local fixture for v1.8-#3.

The inner ``lambda`` captures ``y`` which is bound in the enclosing
function scope ``outer``. Expected resolution: ``y`` -> ``local-in-enclosing``.
"""

from __future__ import annotations


def outer():
    y = 1
    return lambda x: x + y
