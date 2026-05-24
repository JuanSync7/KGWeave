"""Fixture: list/set/dict/generator comprehensions at module scope."""
from __future__ import annotations


SQUARES = [x * x for x in range(10)]
UNIQUE = {y for y in range(10)}
LOOKUP = {k: k * 2 for k in range(5)}
GEN = (z + 1 for z in range(5))
