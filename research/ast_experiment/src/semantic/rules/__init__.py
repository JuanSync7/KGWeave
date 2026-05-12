"""Rule registry — composes RULE_TABLE from every submodule.

Each submodule exports a ``RULES`` list of ``(pyslang.SyntaxKind, callable)``
pairs. Active rule callables carry a ``__rule_id__`` attribute ("S1".."S13");
stubs export an empty ``RULES`` list and pin no metadata.
"""

from __future__ import annotations

from . import (
    hierarchy, dataflow, types, behavior,
    sva, coverage, classes, constraints,
    procedural, clocking, properties, assertions, checkers, extern,
)

ALL_RULE_MODULES = [
    hierarchy, dataflow, types, behavior,
    sva, coverage, classes, constraints,
    procedural, clocking, properties, assertions, checkers, extern,
]


RULE_TABLE: dict = {}
for _mod in ALL_RULE_MODULES:
    for _kind, _fn in _mod.RULES:
        assert _kind not in RULE_TABLE, f"duplicate dispatch for {_kind}"
        RULE_TABLE[_kind] = _fn


__all__ = ["RULE_TABLE", "ALL_RULE_MODULES"]
