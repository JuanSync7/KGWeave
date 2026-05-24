"""Fixture: decorators that must NOT promote ``semantic_role``.

Used by v1.7-#4 decorator-aware connector tests. The connector
promotes a fixed set of three decorator names (``dataclass``,
``pytest.fixture``, ``property``); every other decorator -- including
``functools.cache`` and ``staticmethod`` -- must leave
``semantic_role`` unset.
"""
from __future__ import annotations

import functools


@functools.cache
def cached_fn(x: int) -> int:
    return x * 2


class Helpers:
    @staticmethod
    def util() -> int:
        return 0
