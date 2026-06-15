"""Fixture: async def and a sync def together."""
from __future__ import annotations


async def fetch(url: str) -> str:
    return url


def compute(x: int) -> int:
    return x + 1
