"""Graph mutation helpers — _add_edge / _has_edge / _mark.

Single source of truth: rule modules and the dispatch walker must import
these from here rather than redefining them.
"""

from __future__ import annotations

from typing import Any


def _mark(node: dict[str, Any], **semantic: Any) -> None:
    node["queryable"] = True
    sem = node.setdefault("semantic", {})
    sem.update(semantic)


def _add_edge(graph: dict[str, Any], src: str, dst: str, etype: str, **payload: Any) -> None:
    graph["edges"].append({
        "src": src,
        "dst": dst,
        "type": etype,
        "payload": dict(payload),
    })


def _has_edge(graph: dict[str, Any], src: str, dst: str, etype: str) -> bool:
    for e in graph["edges"]:
        if e["src"] == src and e["dst"] == dst and e["type"] == etype:
            return True
    return False
