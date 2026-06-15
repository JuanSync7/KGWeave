"""Fixture: a class decorated with an aliased ``@dataclass``.

Used by v1.8-#1 alias-aware decorator-semantics connector tests. The
connector must promote ``PyClass.payload.semantic_role`` to
``"dataclass"`` even though the decorator was renamed at import time.
"""
from __future__ import annotations

from dataclasses import dataclass as _dc


@_dc
class AliasedPoint:
    x: int
    y: int
