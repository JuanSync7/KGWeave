"""Fixture: a class decorated with ``@dataclass``.

Used by v1.7-#4 decorator-aware connector tests. The connector must
promote ``PyClass.payload.semantic_role`` to ``"dataclass"`` when one
of the decorator names matches ``dataclass`` or ``dataclasses.dataclass``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Point:
    x: int
    y: int
