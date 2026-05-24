"""Fixture: structural pattern matching (PEP 634, Python 3.10+)."""
from __future__ import annotations


def classify(value: object) -> str:
    match value:
        case int():
            return "int"
        case str():
            return "str"
        case _:
            return "other"
