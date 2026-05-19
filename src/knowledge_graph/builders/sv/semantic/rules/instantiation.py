"""Instantiation rules — S6 + S7 + S13 + S33 + S49.

Owns the pyslang.SyntaxKind set for hierarchy instantiation, parameter
overrides, bind directives, gate-level primitive instantiations, and
anonymous program blocks:

* HierarchyInstantiation
* HierarchicalInstance
* InstanceName
* NamedPortConnection
* ParameterValueAssignment
* NamedParamAssignment
* OrderedParamAssignment
* BindDirective
* PrimitiveInstantiation     (S33)
* AnonymousProgram           (S49)
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
        # S69 — OrderedPortConnection: positional port hookups like
        # ``dut u1(clk, rst, q);``. Sibling of NamedPortConnection below;
        # owns SyntaxKind.OrderedPortConnection via the _s69_stub metadata
        # entry. Runtime lives inline here so hi_gid / inst_path are bound.
        #
        # Direction matches S6 NamedPortConnection: src=parent_net,
        # dst=child_port (inv5 connects-endpoint invariant requires the
        # dst to be a role=port queryable node whose owning module differs
        # from src's). The child port is resolved POSITIONALLY by walking
        # the of_module's ``has_port`` edges in graph (= declaration)
        # order — ordered connections carry no port name lexically, so
        # the LRM positional rule is the only way to map them.
        ordered_child_ports: list[str] = []
        if type_node_id is not None:
            for e in graph["edges"]:
                if (e.get("src") == type_node_id
                        and e.get("type") == "has_port"):
                    ordered_child_ports.append(e["dst"])
        ord_position = 0
        for opc in _descendants(d):
            if _cls(opc) != "OrderedPortConnectionSyntax":
                continue
            ident_toks = _identifier_tokens(opc)
            rhs_name = ident_toks[0].valueText if ident_toks else ""
            # Resolve child port by position; fall back to _unresolved
            # when the of_module isn't in name_index (cross-file forward
            # ref) or when the position overruns the declared port list.
            if ord_position < len(ordered_child_ports):
                dst_id: str = ordered_child_ports[ord_position]
                dst_unresolved = False
            else:
                dst_id = f"_unresolved.{type_name}.__pos_{ord_position}__"
                dst_unresolved = True
            if rhs_name:
                src_id = (name_index.get(f"{scope_path}.{rhs_name}")
                          if scope_path else None)
                if src_id is None:
                    src_id = name_index.get(rhs_name)
            else:
                src_id = None
            if src_id is None:
                # No resolvable RHS — record a leak and skip emitting the
                # connects edge (inv5 requires both endpoints queryable).
                leaks.append({
                    "context": f"ordered_port_connection[{hi_gid}.{ord_position}]",
                    "name": rhs_name or f"__pos_{ord_position}__",
                    "reason": "no_promoted_anchor",
                })
                ord_position += 1
                continue
            payload: dict = {"position": ord_position,
                             "instance": inst_path,
                             "name": rhs_name}
            if dst_unresolved:
                payload["unresolved"] = True
            if not _has_edge(graph, src_id, dst_id, "connects"):
                _add_edge(graph, src_id, dst_id, "connects", **payload)
            ord_position += 1
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
    """S13: BindDirectiveSyntax → bound_into edge.

    S61 inlined here (lesson 4 edge-only kind): an optional
    BindTargetListSyntax child carries an explicit list of target instance
    names — ``bind dut : u1, u2 mon m_inst();``. When present, emit one
    ``bind_target`` edge per IdentifierName under the BindTargetList from
    the binder module to each named instance, preserving source order via
    the ``index`` payload field. Instance name resolution searches the
    semantic name index for any path key ending in ``.<name>`` (the
    instances live at ``<parent_scope>.<name>`` and pyslang gives us only
    the bare name); on a miss the dst falls back to ``_unresolved.<name>``
    with ``unresolved=True``.
    """
    target_name: str | None = None
    hier_inst: Any | None = None
    target_list_node: Any | None = None
    for ch in node:
        if _is_token(ch):
            continue
        kind_name = _cls(ch)
        if kind_name == "IdentifierNameSyntax" and target_name is None:
            toks = _identifier_tokens(ch)
            if toks:
                target_name = toks[0].valueText
        elif kind_name == "BindTargetListSyntax" and target_list_node is None:
            target_list_node = ch
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

    # S61 — BindTargetList: emit one ``bind_target`` edge per named instance
    # in the explicit target list (if any). Lesson 4 edge-only kind — owns
    # the SyntaxKind via the _s61_stub metadata entry below; runtime lives
    # inline here where binder_gid is bound.
    if target_list_node is not None:
        target_names: list[str] = []
        for sub in _descendants(target_list_node):
            if _cls(sub) != "IdentifierNameSyntax":
                continue
            toks = _identifier_tokens(sub)
            if toks:
                target_names.append(toks[0].valueText)
        for ord_idx, tname in enumerate(target_names):
            # Resolve: scan name_index for any path key ending in ``.<tname>``
            # whose value points to an actual semantic node (instances live
            # at ``<parent_scope>.<tname>``; pyslang gives us only the bare
            # name in the target list). Bare-name lookup is the secondary
            # fallback; ``_unresolved.<tname>`` is the final fallback.
            resolved_gid: str | None = None
            suffix = "." + tname
            for key, val in name_index.items():
                if key.endswith(suffix):
                    resolved_gid = val
                    break
            if resolved_gid is None:
                resolved_gid = name_index.get(tname)
            dst = resolved_gid if resolved_gid is not None else f"_unresolved.{tname}"
            payload: dict = {"target": tname, "index": ord_idx,
                             "target_module": target_name}
            if resolved_gid is None:
                payload["unresolved"] = True
            if not _has_edge(graph, binder_gid, dst, "bind_target"):
                _add_edge(graph, binder_gid, dst, "bind_target", **payload)


# --- S33 — gate-level PrimitiveInstantiation --------------------------------

# Map TokenKind name → primitive-gate label. PrimitiveInstantiationSyntax
# carries the gate keyword as a direct Token child (AndKeyword / OrKeyword /
# NotKeyword / NandKeyword / NorKeyword / XorKeyword / XnorKeyword /
# BufKeyword / and the conditional variants). The label is stamped on the
# promoted node's attributes["primitive"] so downstream queries can filter
# by gate type without round-tripping through the token stream.
_PRIMITIVE_KEYWORD_TO_LABEL: dict[str, str] = {
    "AndKeyword": "and",
    "OrKeyword": "or",
    "NotKeyword": "not",
    "NandKeyword": "nand",
    "NorKeyword": "nor",
    "XorKeyword": "xor",
    "XnorKeyword": "xnor",
    "BufKeyword": "buf",
    "BufIf0Keyword": "bufif0",
    "BufIf1Keyword": "bufif1",
    "NotIf0Keyword": "notif0",
    "NotIf1Keyword": "notif1",
}


def _primitive_type_of(node: Any) -> str:
    """Return the gate-type label (``"and"``/``"or"``/...) of a
    PrimitiveInstantiationSyntax, sourced from the leading keyword token.

    Walks direct Token children only — the gate keyword is the FIRST primitive
    keyword to appear before the SeparatedList of HierarchicalInstance
    children. Returns ``""`` if no recognised keyword is present (defensive;
    the LRM grammar guarantees one of the entries in
    ``_PRIMITIVE_KEYWORD_TO_LABEL`` is always present).
    """
    for ch in node:
        if not _is_token(ch):
            continue
        label = _PRIMITIVE_KEYWORD_TO_LABEL.get(_token_kind_name(ch))
        if label is not None:
            return label
    return ""


def _primitive_delay_text(node: Any) -> str:
    """Return the textual delay of a PrimitiveInstantiationSyntax (e.g.
    ``"#5"``) or ``""`` when no delay is specified.

    pyslang surfaces gate delays as a ``DelayControlSyntax`` direct child of
    the PrimitiveInstantiation. Concatenate every Token rawText under that
    node — the result is the source slice (``#5``, ``#(2,3)``, etc.).
    """
    for ch in node:
        if _is_token(ch):
            continue
        # pyslang's class for ``#<expr>`` and ``#(t_rise, t_fall)`` is
        # ``DelaySyntax`` (kind=DelayControl) — NOT ``DelayControlSyntax``.
        # Discriminate via the SyntaxKind to be robust across pyslang
        # versions / grammar variants.
        kind_name = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
        if kind_name == "DelayControl" or _cls(ch) == "DelaySyntax":
            # Reconstruct the source slice by walking every Token rawText
            # under the delay subtree (the leading ``#`` lives on the Hash
            # token; subsequent tokens carry the integer / paren payload).
            parts: list[str] = []

            def _walk(n: Any) -> None:
                if _is_token(n):
                    parts.append(n.rawText)
                    return
                try:
                    kids = list(n)
                except TypeError:
                    return
                for c in kids:
                    _walk(c)

            _walk(ch)
            return "".join(parts).strip()
    return ""


def _primitive_ports_of(inst: Any) -> list[str]:
    """Return the ordered list of port-connection identifier texts under a
    HierarchicalInstance whose parent is a PrimitiveInstantiation.

    Gate primitives use positional connections only; each connection is an
    ``OrderedPortConnectionSyntax`` child of the parenthesised connection
    list. We collect ``_expression_text`` of each so simple identifier
    references (``a``, ``out_and``) round-trip cleanly while richer
    expressions (concatenations, constants) are still surfaced as their
    textual form.
    """
    out: list[str] = []
    for d in _descendants(inst):
        if _cls(d) != "OrderedPortConnectionSyntax":
            continue
        # Walk one level into the connection to find its expression payload.
        expr_text = ""
        for ch in d:
            if _is_token(ch):
                continue
            try:
                kids = list(ch)
            except TypeError:
                kids = []
            if kids or _identifier_tokens(ch):
                expr_text = _expression_text(ch)
                break
        out.append(expr_text)
    return out


def rule_s33(graph, node, gid, gnode, scope, name_index, leaks,
             scope_path="", module_gid=None, **_):
    """S33: PrimitiveInstantiationSyntax → one ``primitive_instance`` node
    per HierarchicalInstance child, edge ``has_primitive_instance`` from
    the enclosing module.

    Mirrors the S6 fan-out pattern: a single primitive-instantiation
    declaration like ``not g_not1 (n_a, a), g_not2 (n_b, b);`` carries
    TWO HierarchicalInstance children and promotes to two semantic nodes.
    The gate type label (``"and"``/``"or"``/...) is shared across all
    instances in the declaration and stamped on each node's
    ``attributes["primitive"]``. The optional ``#5`` delay control (and its
    multi-value cousin ``#(t_rise, t_fall)``) is captured as ``attributes
    ["delay"]`` — empty string when absent. Port connections are extracted
    positionally via ``_primitive_ports_of`` as ``attributes["ports"]``.

    Optional ``drives`` edge: gate primitives connect their output as the
    FIRST positional port. When that port name resolves to a known net /
    port in the shared name index (qualified path first, then bare name),
    emit a ``drives`` edge from the instance node to the target — same
    convention as S19/S20 procedural-drive promotion.
    """
    prim_label = _primitive_type_of(node)
    if not prim_label:
        return
    delay_text = _primitive_delay_text(node)
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
        ports = _primitive_ports_of(d)
        attrs: dict[str, Any] = {
            "primitive": prim_label,
            "ports": list(ports),
        }
        if delay_text:
            attrs["delay"] = delay_text
        _mark(graph["nodes"][idx], role="primitive_instance",
              name=inst_name, path=inst_path, attributes=attrs)
        name_index[inst_path] = hi_gid
        if module_gid is not None and not _has_edge(
            graph, module_gid, hi_gid, "has_primitive_instance"
        ):
            _add_edge(graph, module_gid, hi_gid, "has_primitive_instance")
        # Optional ``drives`` edge from the gate to its output net. Gate
        # primitives use positional connections; per LRM the OUTPUT is the
        # first positional port (for buf/not and all 2+input gates).
        if ports:
            out_name = ports[0]
            if out_name:
                tgt = name_index.get(f"{scope_path}.{out_name}") if scope_path else None
                if tgt is None:
                    tgt = name_index.get(out_name)
                if tgt is not None and tgt != hi_gid and not _has_edge(
                    graph, hi_gid, tgt, "drives"
                ):
                    _add_edge(graph, hi_gid, tgt, "drives",
                              instance=inst_path, port=out_name)


# --- S43 — DefParam / DefParamAssignment legacy parameter override -----------


def _s43_stub(*args, **kwargs):
    """DefParam outer wrapper — consumed by rule_s43 on the inner
    DefParamAssignment (lesson 5 wrapper dedup: register only innermost)."""
    return


def rule_s43(graph, node, gid, gnode, scope, name_index, leaks,
             scope_path="", module_gid=None, **_):
    """S43: DefParamAssignment → ``defparam_override`` edge (edge-only, lesson 4).

    ``defparam u_fifo.DEPTH = 8;`` is fundamentally a cross-hierarchy
    parameter override with no independent identity — it is an edge
    ``(enclosing_module) -[defparam_override]-> (target_param)`` with
    payload ``{"hier_path": "<lhs>", "value": "<rhs_text>"}``.

    Structural navigation (no regex per CLAUDE.md §6 invariant 4):
    - ScopedNameSyntax child → hierarchical target path (token text concat)
    - EqualsValueClauseSyntax child → RHS value via ``_expression_text``

    Target resolution: try ``<inst>.<param>`` qualified against
    name_index; if unresolved, emit ``dst="_unresolved.<hier_path>"`` with
    ``payload["unresolved"]=True`` (lesson 4 fallback).
    """
    if module_gid is None:
        return

    # Walk direct children: ScopedName (lhs) and EqualsValueClause (rhs).
    hier_path_parts: list[str] = []
    value_text: str = ""

    for ch in node:
        if _is_token(ch):
            continue
        ch_cls = _cls(ch)
        if ch_cls == "ScopedNameSyntax":
            # Collect all Identifier token texts under the ScopedName to form
            # the hierarchical path (e.g. "u_fifo.DEPTH").
            for sub in _descendants(ch):
                if _is_token(sub) and _token_kind_name(sub) == "Identifier":
                    hier_path_parts.append(sub.valueText)
        elif ch_cls == "EqualsValueClauseSyntax":
            # Walk past the leading Equals token to the expression node.
            for sub in ch:
                if _is_token(sub):
                    continue
                value_text = _expression_text(sub)
                break

    if not hier_path_parts:
        leaks.append({
            "context": f"defparam[{gid}]",
            "name": "?",
            "reason": "defparam_missing_target_path",
        })
        return

    hier_path = ".".join(hier_path_parts)
    # Target is the last identifier in the scoped path (the param name),
    # qualified under the instance-type module name if possible.
    # hier_path_parts example: ["u_fifo", "DEPTH"]
    # Try: look up the scope_path-qualified instance type to resolve the param.
    target_id: str | None = None
    if len(hier_path_parts) >= 2:
        inst_name = hier_path_parts[0]
        param_name = hier_path_parts[-1]
        # Find the of_module type for the named instance in name_index.
        # First try scope_path.inst_name to get the instance gid, then
        # walk edges to find the ``of_module`` target module, and look up
        # ``<module>.<param>`` in the index.
        qualified_inst = f"{scope_path}.{inst_name}" if scope_path else inst_name
        inst_gid = name_index.get(qualified_inst)
        if inst_gid is not None:
            # Walk the graph edges to find the ``of_module`` edge.
            for e in graph["edges"]:
                if e["src"] == inst_gid and e.get("type") == "of_module":
                    mod_name = e.get("payload", {}).get("name") or ""
                    if mod_name:
                        target_id = name_index.get(f"{mod_name}.{param_name}")
                    break
        if target_id is None:
            # Fallback: bare param name lookup.
            target_id = name_index.get(param_name)

    dst = target_id if target_id is not None else f"_unresolved.{hier_path}"
    payload: dict = {"hier_path": hier_path, "value": value_text}
    if target_id is None:
        payload["unresolved"] = True

    if not _has_edge(graph, module_gid, dst, "defparam_override"):
        _add_edge(graph, module_gid, dst, "defparam_override", **payload)


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


def rule_s49(*args, **kwargs):
    """S49: AnonymousProgram — promotion metadata stub.

    The ``program; ... endprogram`` unnamed program block (SV §24.4) is
    promoted in pass-1 of dispatch.promote via the ``AnonymousProgramSyntax``
    class branch.  That branch uses the lesson-2 subtler variant (push onto
    ``module_stack``) so child declarations inside the anonymous program
    automatically attach to it as their semantic parent — identical to the
    S30 named-program treatment.

    Path key: ``__anon_program_<offset>__`` where ``<offset>`` is the byte
    offset of the ``program`` keyword token (unique per compilation unit).
    Attribute: ``anonymous=True`` distinguishes this node from S30 named
    programs in downstream queries.
    """
    return


rule_s49.__rule_id__ = "S49"


def _s61_stub(*args, **kwargs):
    """S61 ownership marker — BindTargetList is an edge-only kind (lesson 4).

    The connector ``: u1, u2`` inside ``bind dut : u1, u2 mon m_inst();``
    has no independent semantic identity — its runtime promotion lives in
    rule_s13 (the parent's pass-1 branch), emitting one ``bind_target``
    edge per named instance from the binder module to the target instance
    (or to ``_unresolved.<name>`` when the instance is not in the name
    index). This stub exists solely so the bucket1 checklist sees an
    owner for BindTargetList.
    """
    return


_s61_stub.__rule_id__ = "S61"


def _s69_stub(*args, **kwargs):
    """S69 ownership marker — OrderedPortConnection runtime lives inside
    rule_s6 (parent's HierarchicalInstance walk where hi_gid / inst_path
    are bound). This stub exists so the bucket1 checklist sees an owner
    for SyntaxKind.OrderedPortConnection. Lesson 4 edge-only kind — the
    OrderedPortConnection has no independent identity, just a
    ``connects`` edge from the instance to the connected net with a
    ``position`` payload."""
    return


_s69_stub.__rule_id__ = "S69"


rule_s6.__rule_id__ = "S6"
rule_s13.__rule_id__ = "S13"
rule_s33.__rule_id__ = "S33"
rule_s43.__rule_id__ = "S43"
_s43_stub.__rule_id__ = "S43"
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
    (pyslang.SyntaxKind.PrimitiveInstantiation, rule_s33),
    # S43 — DefParam is the wrapper kind (lesson 5: register only innermost).
    # DefParamAssignment is the innermost queryable kind; it carries the
    # ScopedName target and EqualsValueClause RHS.
    (pyslang.SyntaxKind.DefParam, _s43_stub),
    (pyslang.SyntaxKind.DefParamAssignment, rule_s43),
    # S49 — AnonymousProgram: unnamed ``program; ... endprogram`` block.
    # Promotion runs in pass-1 of dispatch.promote (own class
    # AnonymousProgramSyntax, no shared-class ambiguity).
    (pyslang.SyntaxKind.AnonymousProgram, rule_s49),
    # S61 — BindTargetList: edge-only kind (lesson 4). Runtime lives in
    # rule_s13 above (parent's branch where binder_gid is bound); this
    # stub is the ownership marker for the bucket1 checklist.
    (pyslang.SyntaxKind.BindTargetList, _s61_stub),
    # S69 — OrderedPortConnection: positional port hookup form. Edge-only
    # (lesson 4) — runtime lives inside rule_s6 above (where hi_gid and
    # inst_path are bound). This stub is the ownership marker for the
    # bucket1 checklist.
    (pyslang.SyntaxKind.OrderedPortConnection, _s69_stub),
]
