"""Fixture: imports inside ``if TYPE_CHECKING:`` block.

`sys` is a regular runtime import; `collections` is type-only.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import collections


def show() -> None:
    print(sys.version)
