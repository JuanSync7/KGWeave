"""Fixture: a class with ``@property`` methods.

Used by v1.7-#4 decorator-aware connector tests. The connector must
promote ``PyFunction.payload.semantic_role`` to ``"property"`` for any
PyFunction whose outer decorator is ``property``.
"""
from __future__ import annotations


class Circle:
    def __init__(self, r: float) -> None:
        self._r = r

    @property
    def radius(self) -> float:
        return self._r

    @property
    def diameter(self) -> float:
        return self._r * 2
