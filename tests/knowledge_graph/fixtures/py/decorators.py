"""Fixture: decorators on functions and classes.

Used by v1.6-#3 G1 walker/writer tests. The walker must record each
decorator's source expression on the decorated node's payload under
``decorators`` (list[str], outer-most first as written in source).
"""
from __future__ import annotations

import functools


def trace(fn):
    """Runtime decorator used below."""
    return fn


@trace
def plain_decorated() -> int:
    return 1


@functools.lru_cache(maxsize=8)
def parametrised_decorated(x: int) -> int:
    return x * 2


class Box:
    @property
    def value(self) -> int:
        return 42

    @staticmethod
    def helper() -> None:
        return None

    @classmethod
    def make(cls) -> "Box":
        return cls()


@trace
class Decorated:
    pass
