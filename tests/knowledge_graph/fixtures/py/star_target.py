"""Star-import target fixture (v1.10-#3).

Defines a public top-level ``foo`` and a private ``_private``. A consumer
that does ``from star_target import *`` should pick up ``foo`` only.
"""

from __future__ import annotations


def foo(x):
    return x


def _private(x):
    return x
