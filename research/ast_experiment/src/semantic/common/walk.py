"""DFS walk primitives. Sourced verbatim from the legacy scripts/semantic.py."""

from __future__ import annotations

from typing import Any

from .tokens import _is_token


def _walk_with_index(root: Any):
    """Yield ``(dfs_index, syntax_node)`` in lift's DFS order."""
    counter = [0]

    def go(node):
        idx = counter[0]
        counter[0] += 1
        yield idx, node
        try:
            children = list(node)
        except TypeError:
            return
        for c in children:
            yield from go(c)

    yield from go(root)


def _descendants(node: Any):
    yield node
    if _is_token(node):
        return
    try:
        children = list(node)
    except TypeError:
        return
    for c in children:
        yield from _descendants(c)
