"""Fixture: PEP 634 match with mixed pattern kinds for v1.7-#3."""
from __future__ import annotations


def classify(value: object) -> str:
    match value:
        case 1:
            return "literal-int"
        case "a" | "b":
            return "or-str"
        case [x, y]:
            return f"sequence-{x}-{y}"
        case {"k": v}:
            return f"mapping-{v}"
        case Point(px, py) if px > 0:
            return f"class-{px}-{py}"
        case name:
            return f"name-{name}"
        case _:
            return "wildcard"
