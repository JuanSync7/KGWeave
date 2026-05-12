"""Hierarchy rules — S1 (modules/ports/params/nets), S6 (HierarchyInstantiation
+ connects + of_module), S7 (param_override), S11 (interface + modport),
S12 (generate), S13 (bind directive).

S1 / S11 are pass-1 declarative rules — the actual walker logic for them
lives in ``dispatch.promote``. The metadata stubs here exist so the registry
records the rule_id under every relevant pyslang SyntaxKind.
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


# --- Pass-1 declarative kinds (handled inline by dispatch.promote) ---------

def _s1_module_decl(*args, **kwargs):
    """Module/package/interface — promoted in pass 1 of the walker."""
    return


def _s1_port(*args, **kwargs):
    """Port — promoted in pass 1."""
    return


def _s1_param_decl(*args, **kwargs):
    """ParameterDeclaration — pass 1."""
    return


def _s1_variable_port_header(*args, **kwargs):
    """VariablePortHeader — sub-element of ImplicitAnsiPort handled in pass 1."""
    return


def _s1_declarator(*args, **kwargs):
    """Declarator — pass 1 (params/nets/enum-values bind here)."""
    return


def _s11_modport_explicit_port(*args, **kwargs):
    return


def _s11_modport_clocking_port(*args, **kwargs):
    return


def _s11_modport_subroutine_port(*args, **kwargs):
    return


def _s11_modport_simple_port_list(*args, **kwargs):
    return


def _s11_modport_subroutine_port_list(*args, **kwargs):
    return


def _s11_interface(*args, **kwargs):
    """InterfaceDeclaration — pass 1 (handled by the same module branch)."""
    return


def _s11_modport_decl(*args, **kwargs):
    """ModportDeclaration — pass 1."""
    return


def _s11_modport_item(*args, **kwargs):
    """ModportItem — pass 1."""
    return


def _s11_modport_named_port(*args, **kwargs):
    """ModportNamedPort — pass 1."""
    return


_s1_module_decl.__rule_id__ = "S1"
_s1_port.__rule_id__ = "S1"
_s1_param_decl.__rule_id__ = "S1"
_s1_variable_port_header.__rule_id__ = "S1"
_s1_declarator.__rule_id__ = "S1"
_s11_interface.__rule_id__ = "S11a"
_s11_modport_decl.__rule_id__ = "S11b"
_s11_modport_item.__rule_id__ = "S11b"
_s11_modport_named_port.__rule_id__ = "S11b"
_s11_modport_explicit_port.__rule_id__ = "S11b"
_s11_modport_clocking_port.__rule_id__ = "S11b"
_s11_modport_subroutine_port.__rule_id__ = "S11b"
_s11_modport_simple_port_list.__rule_id__ = "S11b"
_s11_modport_subroutine_port_list.__rule_id__ = "S11b"


# --- Active pass-2 rules ----------------------------------------------------


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


def rule_s12(graph, node, gid, gnode, scope, name_index, leaks,
             scope_path="", module_gid=None, **_):
    """S12: LoopGenerateSyntax + elaborated GenerateBlockSyntax instances."""
    label = None
    for d in _descendants(node):
        if _cls(d) != "GenerateBlockSyntax":
            continue
        saw_colon = False
        for tok2 in _descendants(d):
            if _is_token(tok2) and _token_kind_name(tok2) == "Colon":
                saw_colon = True
                continue
            if saw_colon and _is_token(tok2) and _token_kind_name(tok2) == "Identifier":
                label = tok2.valueText
                break
        break
    if scope is None or label is None:
        anon_path = f"{scope_path}.<unlabeled>" if scope_path else "<unlabeled>"
        _mark(gnode, role="generate_loop", name=label or "<unlabeled>",
              path=anon_path, label=label)
        return
    gen_array = None
    try:
        for sym in scope:
            if (type(sym).__name__ == "GenerateBlockArraySymbol"
                    and getattr(sym, "name", "") == label):
                gen_array = sym
                break
    except Exception:
        gen_array = None
    if gen_array is None:
        loop_path = f"{scope_path}.{label}" if scope_path else label
        _mark(gnode, role="generate_loop", name=label, path=loop_path, label=label)
        return
    try:
        entries = list(gen_array.entries)
    except Exception:
        entries = []
    loop_path = f"{scope_path}.{label}" if scope_path else label
    _mark(gnode, role="generate_loop", name=label, path=loop_path,
          label=label, iter_count=len(entries))
    name_index[loop_path] = gid
    if module_gid is not None and not _has_edge(graph, module_gid, gid, "has_generate"):
        _add_edge(graph, module_gid, gid, "has_generate")
    nodes_list_local = graph["nodes"]
    for i, blk in enumerate(entries):
        blk_path = getattr(blk, "hierarchicalPath", "") or f"{scope_path}.{label}[{i}]"
        if blk_path.startswith("$root."):
            blk_path = blk_path[len("$root."):]
        blk_id = f"gen:{blk_path}"
        nodes_list_local.append({
            "id": blk_id,
            "type": "GenerateBlockSyntax",
            "kind": "GenerateBlock",
            "is_token": False,
            "payload": {"synthetic": True, "iteration": i},
            "queryable": True,
            "semantic": {"role": "generate_block",
                         "name": f"{label}[{i}]",
                         "path": blk_path},
        })
        _add_edge(graph, gid, blk_id, "contains_block")
        name_index[blk_path] = blk_id
        for sub in blk:
            if type(sub).__name__ != "InstanceSymbol":
                continue
            inst_name = getattr(sub, "name", "")
            inst_path = getattr(sub, "hierarchicalPath", "") or f"{blk_path}.{inst_name}"
            if inst_path.startswith("$root."):
                inst_path = inst_path[len("$root."):]
            def_name = sub.body.name if getattr(sub, "body", None) else ""
            inst_id = f"gen:{inst_path}"
            nodes_list_local.append({
                "id": inst_id,
                "type": "HierarchicalInstanceSyntax",
                "kind": "HierarchicalInstance",
                "is_token": False,
                "payload": {"synthetic": True},
                "queryable": True,
                "semantic": {"role": "instance", "name": inst_name,
                             "path": inst_path, "of_module": def_name},
            })
            name_index[inst_path] = inst_id
            _add_edge(graph, blk_id, inst_id, "instantiates")
            def_id = (name_index.get("module:" + def_name)
                      or name_index.get("interface:" + def_name)
                      or name_index.get(def_name))
            if def_id is not None:
                _add_edge(graph, inst_id, def_id, "of_module")


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


def _s12_generate_block(*args, **kwargs):
    return


def _s12_if_generate(*args, **kwargs):
    return


def _s12_case_generate(*args, **kwargs):
    return


def _s12_generate_region(*args, **kwargs):
    return


rule_s6.__rule_id__ = "S6"
rule_s12.__rule_id__ = "S12a"
rule_s13.__rule_id__ = "S13"
_s6_hierarchical_instance.__rule_id__ = "S6"
_s6_instance_name.__rule_id__ = "S6"
_s6_named_port_connection.__rule_id__ = "S6"
_s7_param_value_assignment.__rule_id__ = "S7"
_s7_named_param_assignment.__rule_id__ = "S7"
_s7_ordered_param_assignment.__rule_id__ = "S7"
_s12_generate_block.__rule_id__ = "S12b"
_s12_if_generate.__rule_id__ = "S12c"
_s12_case_generate.__rule_id__ = "S12c"
_s12_generate_region.__rule_id__ = "S12c"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ModuleDeclaration, _s1_module_decl),
    (pyslang.SyntaxKind.ImplicitAnsiPort, _s1_port),
    (pyslang.SyntaxKind.VariablePortHeader, _s1_variable_port_header),
    (pyslang.SyntaxKind.ParameterDeclaration, _s1_param_decl),
    (pyslang.SyntaxKind.Declarator, _s1_declarator),
    (pyslang.SyntaxKind.InterfaceDeclaration, _s11_interface),
    (pyslang.SyntaxKind.ModportDeclaration, _s11_modport_decl),
    (pyslang.SyntaxKind.ModportItem, _s11_modport_item),
    (pyslang.SyntaxKind.ModportNamedPort, _s11_modport_named_port),
    (pyslang.SyntaxKind.ModportExplicitPort, _s11_modport_explicit_port),
    (pyslang.SyntaxKind.ModportClockingPort, _s11_modport_clocking_port),
    (pyslang.SyntaxKind.ModportSubroutinePort, _s11_modport_subroutine_port),
    (pyslang.SyntaxKind.ModportSimplePortList, _s11_modport_simple_port_list),
    (pyslang.SyntaxKind.ModportSubroutinePortList, _s11_modport_subroutine_port_list),
    (pyslang.SyntaxKind.HierarchyInstantiation, rule_s6),
    (pyslang.SyntaxKind.HierarchicalInstance, _s6_hierarchical_instance),
    (pyslang.SyntaxKind.InstanceName, _s6_instance_name),
    (pyslang.SyntaxKind.NamedPortConnection, _s6_named_port_connection),
    (pyslang.SyntaxKind.ParameterValueAssignment, _s7_param_value_assignment),
    (pyslang.SyntaxKind.NamedParamAssignment, _s7_named_param_assignment),
    (pyslang.SyntaxKind.OrderedParamAssignment, _s7_ordered_param_assignment),
    (pyslang.SyntaxKind.LoopGenerate, rule_s12),
    (pyslang.SyntaxKind.GenerateBlock, _s12_generate_block),
    (pyslang.SyntaxKind.IfGenerate, _s12_if_generate),
    (pyslang.SyntaxKind.CaseGenerate, _s12_case_generate),
    (pyslang.SyntaxKind.GenerateRegion, _s12_generate_region),
    (pyslang.SyntaxKind.BindDirective, rule_s13),
]
