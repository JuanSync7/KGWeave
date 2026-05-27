"""Top-level mod for v1.11-#3 2-dot relative-import resolution.

Sibling of the ``sub/`` package. ``qual_pkg.sub.consumer`` does
``from ..mod import foo as top_foo`` which must resolve to
``qual_pkg.mod``.
"""

from __future__ import annotations


def foo(x):
    return x
