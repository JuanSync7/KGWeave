"""Reverse: graph -> nested elab_json -> SV text.

`unlift(graph)` rebuilds the structural tree of dicts from the flat node/edge
lists (mirroring the original pyslang syntax tree). `emit(graph)` then walks
that tree depth-first and produces text by concatenating, for every Token leaf,
its leading trivia raw text followed by its rawText. No regex; pure structural
emission.
"""

from __future__ import annotations

from typing import Any


def unlift(graph: dict[str, Any]) -> dict[str, Any]:
    """Reassemble the structural tree from the flat graph."""
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    children: dict[str, list[tuple[int, str]]] = {}
    for e in graph["edges"]:
        if e.get("type") != "child":
            continue
        children.setdefault(e["src"], []).append((e["payload"]["index"], e["dst"]))
    for k in children:
        children[k].sort(key=lambda p: p[0])

    def build(nid: str) -> dict[str, Any]:
        node = nodes_by_id[nid]
        out: dict[str, Any] = {
            "id": nid,
            "type": node["type"],
            "kind": node["kind"],
            "is_token": node["is_token"],
            "payload": dict(node.get("payload") or {}),
            "children": [],
        }
        for _idx, cid in children.get(nid, []):
            out["children"].append(build(cid))
        return out

    root_id = graph["order"][0]
    return build(root_id)


def _emit_node(elab: dict[str, Any], out: list[str]) -> None:
    if elab["is_token"]:
        for tr in elab["payload"].get("trivia", []):
            out.append(tr["text"])
        out.append(elab["payload"].get("rawText", ""))
        return
    for child in elab["children"]:
        _emit_node(child, out)


def emit(graph: dict[str, Any]) -> str:
    """Lift's inverse: produce SV source text from the graph."""
    elab = unlift(graph)
    pieces: list[str] = []
    _emit_node(elab, pieces)
    return "".join(pieces)
