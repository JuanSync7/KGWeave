"""Fixture: walrus operator inside one function, not the other."""
from __future__ import annotations


def with_walrus(items: list[int]) -> int:
    if (n := len(items)) > 0:
        return n
    return 0


def no_walrus(items: list[int]) -> int:
    n = len(items)
    if n > 0:
        return n
    return 0
