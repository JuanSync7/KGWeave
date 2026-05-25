"""Fixture: ``property`` rebound under a local alias used as decorator.

Rare but legal pattern (``from builtins import property as prop``). The
v1.8-#1 alias-aware connector must still promote ``radius`` to
``semantic_role="property"`` via the per-file import-rename map.

Also includes a ``cached_property as cp`` negative control: the bare
canonical ``functools.cached_property`` is NOT in the closed promotion
table, so promotion through the alias must NOT happen either.
"""
from __future__ import annotations

from builtins import property as prop
from functools import cached_property as cp


class Circle:
    def __init__(self, r: float) -> None:
        self._r = r

    @prop
    def radius(self) -> float:
        return self._r

    @cp
    def diameter(self) -> float:
        return self._r * 2
