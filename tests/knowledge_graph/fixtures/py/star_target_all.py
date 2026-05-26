"""Star-import target with explicit ``__all__`` (v1.10-#3).

``__all__`` lists only ``bar``; ``baz`` is defined but NOT exported and
must not flow through a consumer's ``from star_target_all import *``.
"""

from __future__ import annotations

__all__ = ["bar"]


def bar(x):
    return x


def baz(x):
    return x
