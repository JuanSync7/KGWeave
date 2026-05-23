"""A small Python fixture for the v1 builder.

Has every kind v1 covers: module docstring, one import, one
top-level function (with type hints), one class with one method.
"""

from __future__ import annotations

import math


def add(x: int, y: int) -> int:
    """Return x + y."""
    return x + y


class Counter:
    """Stateful counter — exercises class + method lift."""

    def __init__(self, start: int = 0) -> None:
        self.value = start

    def bump(self) -> int:
        self.value += 1
        return self.value


_PI: float = math.pi
