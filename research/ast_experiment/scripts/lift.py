"""Forward: pyslang SyntaxTree -> graph (nodes, edges, order).

Lift is class-agnostic and structural. For every pyslang syntax node we create
a graph node typed by class name + SyntaxKind, and for every child reachable
by iter(node) we add an ordered "child" edge to the corresponding graph node.

Token leaves carry their lexical payload (kind, rawText, leading trivia) so the
reverse engine can reconstruct text without consulting source strings. No regex
is used; child enumeration relies solely on pyslang's iterable SyntaxNode API.

Graph shape:
    {
      "nodes": [
        {"id": str, "type": class_name, "kind": syntax_or_token_kind,
         "is_token": bool,
         "payload": {...}},
        ...
      ],
      "edges": [
        {"src": parent_id, "dst": child_id, "type": "child",
         "payload": {"index": int}},
        ...
      ],
      "order": [root_id],
    }
"""

from __future__ import annotations

from typing import Any


def _trivia_records(token: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for tr in token.trivia:
        out.append({"kind": str(tr.kind), "text": tr.getRawText()})
    return out


class _Builder:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._counter = 0

    def _new_id(self, cls_name: str) -> str:
        self._counter += 1
        return f"n{self._counter:04d}.{cls_name}"

    def visit(self, node: Any) -> str:
        cls_name = type(node).__name__
        nid = self._new_id(cls_name)
        if cls_name == "Token":
            payload = {
                "rawText": node.rawText,
                "valueText": node.valueText,
                "trivia": _trivia_records(node),
                "isMissing": bool(node.isMissing),
            }
            self.nodes.append({
                "id": nid,
                "type": "Token",
                "kind": str(node.kind),
                "is_token": True,
                "payload": payload,
            })
            return nid
        # Container syntax node — record kind and recurse.
        kind = str(getattr(node, "kind", ""))
        self.nodes.append({
            "id": nid,
            "type": cls_name,
            "kind": kind,
            "is_token": False,
            "payload": {},
        })
        # Iterate ordered children.
        try:
            children = list(node)
        except TypeError:
            children = []
        for idx, child in enumerate(children):
            child_id = self.visit(child)
            self.edges.append({
                "src": nid,
                "dst": child_id,
                "type": "child",
                "payload": {"index": idx},
            })
        return nid


def lift(tree: Any) -> dict[str, Any]:
    """Convert a pyslang SyntaxTree into the structural graph dict."""
    builder = _Builder()
    root_id = builder.visit(tree.root)
    return {
        "nodes": builder.nodes,
        "edges": builder.edges,
        "order": [root_id],
    }
