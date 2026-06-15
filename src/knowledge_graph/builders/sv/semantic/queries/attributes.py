"""Attribute queries — width / default-value reconstruction from typed child
edges and lifted Token rawText payloads. Zero regex, zero source-string slicing."""

from __future__ import annotations

from typing import Any

from .connectivity import find_by_name


def _children_of(graph: dict[str, Any], nid: str) -> list[str]:
    out: list[tuple[int, str]] = []
    for e in graph["edges"]:
        if e["type"] != "child" or e["src"] != nid:
            continue
        out.append((e["payload"].get("index", 0), e["dst"]))
    out.sort()
    return [d for _, d in out]


def _parent_of(graph: dict[str, Any], nid: str) -> str | None:
    for e in graph["edges"]:
        if e["type"] == "child" and e["dst"] == nid:
            return e["src"]
    return None


def _text_of_subtree(graph: dict[str, Any], nid: str, include_leading_trivia: bool = False) -> str:
    """Reconstruct the raw token text under ``nid`` from typed Token payloads."""
    by_id = {n["id"]: n for n in graph["nodes"]}
    first = [True]

    def visit(x: str) -> str:
        n = by_id[x]
        if n.get("is_token"):
            payload = n.get("payload", {})
            tx = ""
            if include_leading_trivia or not first[0]:
                for tr in payload.get("trivia", []):
                    tx += tr.get("text", "")
            first[0] = False
            return tx + payload.get("rawText", "")
        s = ""
        for c in _children_of(graph, x):
            s += visit(c)
        return s

    return visit(nid)


def _first_child_of_kind(graph: dict[str, Any], nid: str, kinds: set[str]) -> str | None:
    by_id = {n["id"]: n for n in graph["nodes"]}
    for c in _children_of(graph, nid):
        if by_id[c]["type"] in kinds:
            return c
    return None


def _descendants_of_kind(graph: dict[str, Any], nid: str, kinds: set[str]) -> list[str]:
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[str] = []
    stack = [nid]
    while stack:
        x = stack.pop()
        if by_id[x]["type"] in kinds:
            out.append(x)
        for c in reversed(_children_of(graph, x)):
            stack.append(c)
    return out


def width_of(graph: dict[str, Any], net_or_port_path: str) -> dict[str, Any]:
    """Return the structural width of a net or port."""
    target = find_by_name(graph, net_or_port_path)
    if target is None:
        return {"packed_dim": None, "unpacked_dim": None, "data_type": None}
    by_id = {n["id"]: n for n in graph["nodes"]}
    role = target.get("semantic", {}).get("role")
    nid = target["id"]

    if role == "port":
        header = _first_child_of_kind(graph, nid, {"VariablePortHeaderSyntax"})
        decl = _first_child_of_kind(graph, nid, {"DeclaratorSyntax"})
    else:
        decl = nid
        sep_list = _parent_of(graph, nid)
        data_decl = _parent_of(graph, sep_list) if sep_list else None
        if data_decl is not None and by_id[data_decl]["type"] == "DataDeclarationSyntax":
            header = _first_child_of_kind(graph, data_decl,
                                          {"IntegerTypeSyntax", "NamedTypeSyntax",
                                           "ImplicitTypeSyntax"})
        else:
            header = None

    packed = None
    data_type = None
    if header is not None:
        _TYPE_KEYWORDS = {"LogicKeyword", "RegKeyword", "WireKeyword",
                          "BitKeyword", "ByteKeyword", "ShortIntKeyword",
                          "IntKeyword", "LongIntKeyword", "IntegerKeyword"}
        stack = [header]
        while stack:
            x = stack.pop()
            cn = by_id[x]
            if cn.get("is_token"):
                kind_name = cn.get("kind", "").rsplit(".", 1)[-1]
                if kind_name in _TYPE_KEYWORDS:
                    data_type = cn["payload"].get("valueText")
                    break
                continue
            for c in reversed(_children_of(graph, x)):
                stack.append(c)
        dims = _descendants_of_kind(graph, header, {"VariableDimensionSyntax"})
        if dims:
            packed = "".join(_text_of_subtree(graph, d) for d in dims).lstrip()

    unpacked = None
    if decl is not None:
        for c in _children_of(graph, decl):
            cn = by_id[c]
            if cn["type"] == "SyntaxNode" and "SyntaxList" in cn.get("kind", ""):
                dims = _descendants_of_kind(graph, c, {"VariableDimensionSyntax"})
                if dims:
                    unpacked = "".join(_text_of_subtree(graph, d) for d in dims).lstrip()
                    break

    return {"packed_dim": packed, "unpacked_dim": unpacked, "data_type": data_type}


def default_value_of(graph: dict[str, Any], param_path: str) -> str | None:
    """Return the textual default expression of a parameter, or ``None``."""
    target = find_by_name(graph, param_path)
    if target is None:
        return None
    by_id = {n["id"]: n for n in graph["nodes"]}
    nid = target["id"]
    eq_clause = _first_child_of_kind(graph, nid, {"EqualsValueClauseSyntax"})
    if eq_clause is None:
        return None
    saw_eq = False
    for c in _children_of(graph, eq_clause):
        cn = by_id[c]
        if cn.get("is_token") and cn.get("kind", "").endswith(".Equals"):
            saw_eq = True
            continue
        if not saw_eq:
            continue
        text = _text_of_subtree(graph, c).strip()
        return text if text else None
    return None
