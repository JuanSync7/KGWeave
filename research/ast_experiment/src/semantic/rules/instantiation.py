"""Instantiation rules — S6 + S7 + S13.

Owns the pyslang.SyntaxKind set for hierarchy instantiation, parameter
overrides, and bind directives:

* HierarchyInstantiation
* HierarchicalInstance
* InstanceName
* NamedPortConnection
* ParameterValueAssignment
* NamedParamAssignment
* OrderedParamAssignment
* BindDirective
"""

from __future__ import annotations

from typing import Any

import pyslang

from ..common.graph import _add_edge, _has_edge, _mark
from ..common.tokens import (
    _cls,
    _expression_text,
    _identifier_tokens,
    _is_token,
    _token_kind_name,
)
from ..common.walk import _descendants


def _gid_for_subtree(graph, parent_gid, target_class, target_inst=None):
    """Find a descendant graph-node id of ``parent_gid`` whose type matches
    ``target_class``."""
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    children_by_src: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e.get("type") != "child":
            continue
        children_by_src.setdefault(e["src"], []).append(e["dst"])
    stack = [parent_gid]
    matches: list[str] = []
    while stack:
        cur = stack.pop()
        n = nodes_by_id.get(cur)
        if n is None:
            continue
        if n["type"] == target_class:
            matches.append(cur)
        kids = children_by_src.get(cur, [])
        stack.extend(reversed(kids))
    if not matches:
        return None
    if target_inst is None:
        return matches[0]
    for m in matches:
        sub_stack = [m]
        while sub_stack:
            x = sub_stack.pop()
            xn = nodes_by_id.get(x)
            if xn is None:
                continue
            if xn.get("is_token") and xn.get("payload", {}).get("valueText") == target_inst:
                return m
            sub_stack.extend(children_by_src.get(x, []))
    return matches[0]


def _node_index_by_id(graph, target_id):
    for i, n in enumerate(graph["nodes"]):
        if n["id"] == target_id:
            return i
    return None


def rule_s6(graph, node, gid, gnode, scope, name_index, leaks,
            scope_path="", module_gid=None, **_):
    """S6: HierarchyInstantiationSyntax → instance + of_module + connects.

    Also embeds S7 — extracting ParameterValueAssignmentSyntax overrides
    inline since the override block applies to every instance in the same
    declaration.
    """
    type_name = None
    for ch in node:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier":
            type_name = ch.valueText
            break
    if type_name is None:
        for ch in node:
            if _is_token(ch):
                continue
            toks = _identifier_tokens(ch)
            if toks:
                type_name = toks[0].valueText
                break
    if type_name is None:
        return
    # S28 — a HierarchyInstantiationSyntax whose type name resolves to a
    # promoted checker (not a module/interface) is a checker instantiation
    # at module body scope. Pyslang parses it as HierarchyInstantiation
    # because the parser cannot disambiguate from module instantiation at
    # parse time; pass-1 marked the checker declaration with a
    # ``checker:<name>`` name-index entry. When that lookup hits, emit
    # ``has_checker_instance`` (from the enclosing module) and ``of_checker``
    # (from the instance to the checker definition) and stamp the
    # HierarchicalInstance as role=checker_instance — keeping checker-style
    # queries cleanly separated from module-instance queries.
    checker_target_id = name_index.get("checker:" + type_name)
    if checker_target_id is not None:
        for d in _descendants(node):
            if _cls(d) != "HierarchicalInstanceSyntax":
                continue
            inst_name = None
            for ch in d:
                if _cls(ch) == "InstanceNameSyntax":
                    toks = _identifier_tokens(ch)
                    if toks:
                        inst_name = toks[0].valueText
                    break
            if inst_name is None:
                continue
            inst_path = f"{scope_path}.{inst_name}" if scope_path else inst_name
            hi_gid = _gid_for_subtree(graph, gid, "HierarchicalInstanceSyntax",
                                      target_inst=inst_name)
            if hi_gid is None:
                continue
            idx = _node_index_by_id(graph, hi_gid)
            if idx is None:
                continue
            _mark(graph["nodes"][idx], role="checker_instance",
                  name=inst_name, path=inst_path,
                  attributes={"checker_name": type_name})
            name_index[inst_path] = hi_gid
            if module_gid is not None and not _has_edge(
                graph, module_gid, hi_gid, "has_checker_instance"
            ):
                _add_edge(graph, module_gid, hi_gid, "has_checker_instance")
            if not _has_edge(graph, hi_gid, checker_target_id, "of_checker"):
                _add_edge(graph, hi_gid, checker_target_id, "of_checker",
                          name=type_name)
        return
    type_node_id = (name_index.get("module:" + type_name)
                    or name_index.get("interface:" + type_name)
                    or name_index.get(type_name))
    overrides: list[tuple[str, str]] = []
    pva = next((c for c in node if _cls(c) == "ParameterValueAssignmentSyntax"), None)
    if pva is not None:
        named_seen = False
        for npa in _descendants(pva):
            if _cls(npa) != "NamedParamAssignmentSyntax":
                continue
            named_seen = True
            children = list(npa)
            pname = None
            expr_text = None
            saw_dot = False
            saw_open = False
            for ch in children:
                if _is_token(ch) and _token_kind_name(ch) == "Dot":
                    saw_dot = True
                    continue
                if saw_dot and pname is None and _is_token(ch) and _token_kind_name(ch) == "Identifier":
                    pname = ch.valueText
                    continue
                if _is_token(ch) and _token_kind_name(ch) == "OpenParenthesis":
                    saw_open = True
                    continue
                if saw_open and not _is_token(ch):
                    try:
                        sub_kids = list(ch)
                    except TypeError:
                        sub_kids = []
                    if sub_kids or _identifier_tokens(ch):
                        expr_text = _expression_text(ch)
                        break
            if pname is not None and expr_text is not None:
                overrides.append((pname, expr_text))
        if not named_seen:
            pass

    for d in _descendants(node):
        if _cls(d) != "HierarchicalInstanceSyntax":
            continue
        inst_name = None
        for ch in d:
            if _cls(ch) == "InstanceNameSyntax":
                toks = _identifier_tokens(ch)
                if toks:
                    inst_name = toks[0].valueText
                break
        if inst_name is None:
            continue
        inst_path = f"{scope_path}.{inst_name}" if scope_path else inst_name
        hi_gid = _gid_for_subtree(graph, gid, "HierarchicalInstanceSyntax",
                                  target_inst=inst_name)
        if hi_gid is None:
            continue
        idx = _node_index_by_id(graph, hi_gid)
        if idx is None:
            continue
        _mark(graph["nodes"][idx], role="instance", name=inst_name,
              path=inst_path, of_module=type_name)
        name_index[inst_path] = hi_gid
        if module_gid is not None and not _has_edge(graph, module_gid, hi_gid, "instantiates"):
            _add_edge(graph, module_gid, hi_gid, "instantiates")
        if type_node_id is not None and not _has_edge(graph, hi_gid, type_node_id, "of_module"):
            _add_edge(graph, hi_gid, type_node_id, "of_module")
        for pname, pvalue in overrides:
            child_param_id = name_index.get(f"{type_name}.{pname}")
            if child_param_id is None:
                leaks.append({
                    "context": f"param_override[{inst_path}]",
                    "name": pname,
                    "reason": "no_child_param_anchor",
                })
                continue
            if not _has_edge(graph, hi_gid, child_param_id, "param_override"):
                _add_edge(graph, hi_gid, child_param_id, "param_override",
                          instance=inst_path, name=pname, value=pvalue)
        for npc in _descendants(d):
            if _cls(npc) != "NamedPortConnectionSyntax":
                continue
            children = list(npc)
            port_name = None
            expr_node = None
            saw_dot = False
            for ch in children:
                if _is_token(ch) and _token_kind_name(ch) == "Dot":
                    saw_dot = True
                    continue
                if saw_dot and _is_token(ch) and _token_kind_name(ch) == "Identifier" and port_name is None:
                    port_name = ch.valueText
                    continue
                if port_name is not None and not _is_token(ch):
                    try:
                        sub_kids = list(ch)
                    except TypeError:
                        sub_kids = []
                    if sub_kids or _identifier_tokens(ch):
                        expr_node = ch
                        break
            if port_name is None:
                continue
            port_path = f"{inst_path}.{port_name}"
            child_port_id = name_index.get(f"{type_name}.{port_name}")
            if child_port_id is not None:
                name_index[port_path] = child_port_id
            rhs_names: list[str] = []
            if expr_node is not None:
                for tok in _identifier_tokens(expr_node):
                    rhs_names.append(tok.valueText)
            for rname in rhs_names:
                src_id = name_index.get(f"{scope_path}.{rname}")
                if src_id is None:
                    leaks.append({
                        "context": f"port_connection.rhs[{hi_gid}.{port_name}]",
                        "name": rname,
                        "reason": "no_promoted_anchor",
                    })
                    continue
                dst_id = child_port_id if child_port_id is not None else hi_gid
                if not _has_edge(graph, src_id, dst_id, "connects"):
                    _add_edge(graph, src_id, dst_id, "connects",
                              instance=inst_path, port=port_name)


def rule_s13(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S13: BindDirectiveSyntax → bound_into edge."""
    target_name: str | None = None
    hier_inst: Any | None = None
    for ch in node:
        if _is_token(ch):
            continue
        kind_name = _cls(ch)
        if kind_name == "IdentifierNameSyntax" and target_name is None:
            toks = _identifier_tokens(ch)
            if toks:
                target_name = toks[0].valueText
        elif kind_name == "HierarchyInstantiationSyntax" and hier_inst is None:
            hier_inst = ch
    if target_name is None or hier_inst is None:
        leaks.append({"context": f"bind_directive[{gid}]",
                      "name": target_name or "?",
                      "reason": "bind_directive_missing_target_or_instantiation"})
        return
    binder_name: str | None = None
    inst_name: str | None = None
    for ch in hier_inst:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier" and binder_name is None:
            binder_name = ch.valueText
            break
    for d in _descendants(hier_inst):
        if _cls(d) == "InstanceNameSyntax":
            toks = _identifier_tokens(d)
            if toks:
                inst_name = toks[0].valueText
                break
    if binder_name is None:
        leaks.append({"context": f"bind_directive[{gid}]",
                      "name": "?",
                      "reason": "bind_directive_missing_binder_type"})
        return
    target_gid = name_index.get("module:" + target_name) or name_index.get(target_name)
    binder_gid = name_index.get("module:" + binder_name) or name_index.get(binder_name)
    if target_gid is None:
        leaks.append({"context": f"bind_directive[{gid}]",
                      "name": target_name,
                      "reason": "bind_target_unresolved"})
        return
    if binder_gid is None:
        leaks.append({"context": f"bind_directive[{gid}]",
                      "name": binder_name,
                      "reason": "bind_binder_unresolved"})
        return
    scope_str = gid.split(":", 1)[0] if ":" in gid else ""
    if not _has_edge(graph, binder_gid, target_gid, "bound_into"):
        _add_edge(graph, binder_gid, target_gid, "bound_into",
                  instance_name=inst_name or "", scope=scope_str)


# Metadata-only entries — sub-elements handled inside the active rules above.

def _s6_hierarchical_instance(*args, **kwargs):
    """HierarchicalInstance is consumed by rule_s6's descendants walk."""
    return


def _s6_instance_name(*args, **kwargs):
    return


def _s6_named_port_connection(*args, **kwargs):
    return


def _s7_param_value_assignment(*args, **kwargs):
    """ParameterValueAssignment is consumed by rule_s6 in-place."""
    return


def _s7_named_param_assignment(*args, **kwargs):
    return


def _s7_ordered_param_assignment(*args, **kwargs):
    return


rule_s6.__rule_id__ = "S6"
rule_s13.__rule_id__ = "S13"
_s6_hierarchical_instance.__rule_id__ = "S6"
_s6_instance_name.__rule_id__ = "S6"
_s6_named_port_connection.__rule_id__ = "S6"
_s7_param_value_assignment.__rule_id__ = "S7"
_s7_named_param_assignment.__rule_id__ = "S7"
_s7_ordered_param_assignment.__rule_id__ = "S7"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.HierarchyInstantiation, rule_s6),
    (pyslang.SyntaxKind.HierarchicalInstance, _s6_hierarchical_instance),
    (pyslang.SyntaxKind.InstanceName, _s6_instance_name),
    (pyslang.SyntaxKind.NamedPortConnection, _s6_named_port_connection),
    (pyslang.SyntaxKind.ParameterValueAssignment, _s7_param_value_assignment),
    (pyslang.SyntaxKind.NamedParamAssignment, _s7_named_param_assignment),
    (pyslang.SyntaxKind.OrderedParamAssignment, _s7_ordered_param_assignment),
    (pyslang.SyntaxKind.BindDirective, rule_s13),
]
