"""Dispatch walker — owns the two-pass DFS over the syntax tree and the
``RULE_TABLE``-driven projection.

The walker preserves the legacy guard machinery (``in_generate``, ``in_bind``,
function-body skip) as walker context — these are not the responsibility of
individual rule modules.

Pass 1 (declarative): promote modules / ports / params / nets / typedefs /
functions / modports / packages / interfaces. Builds the cross-file
``semantic_name_index``.

Pass 2 (dispatched): look up the active rule for each node's ``pyslang.kind``
in ``RULE_TABLE`` and invoke it. Rules whose ``__rule_id__`` is in {S1, S9*,
S10, S11*, S6/S7/S12 sub-elements} are no-ops at the dispatch site — their
work is already done in pass 1 or by an enclosing active rule.
"""

from __future__ import annotations

from typing import Any

from .common.graph import _add_edge, _has_edge, _mark
from .common.resolve import _all_module_scopes
from .common.tokens import (
    _cls,
    _function_name_of,
    _identifier_tokens,
    _is_token,
    _module_name_of,
    _property_name_of,
    _sequence_name_of,
    _token_kind_name,
    _typedef_name_of,
)
from .rules import RULE_TABLE
from .rules.dataflow import rule_s3_or_s8
from .rules.generate import rule_s12
from .rules.instantiation import rule_s6, rule_s13


# Active pass-2 rules — these are the only RULE_TABLE entries whose callable
# actually has side effects on the graph. All others are metadata stubs.
_PASS2_ACTIVE: set = set()
# Populated lazily — we resolve by checking the function's __rule_id__ against
# a known-active set.
_ACTIVE_RULE_IDS = {"S2", "S3", "S4", "S5", "S6", "S8", "S12a", "S13"}


def _is_active(fn) -> bool:
    rid = getattr(fn, "__rule_id__", None)
    return rid in _ACTIVE_RULE_IDS


def promote(
    graph: dict[str, Any],
    syntax_tree: Any,
    compilation: Any,
    *,
    node_offset: int | None = None,
    phase: str | None = None,
) -> None:
    """Apply S1..S13 in a single two-pass DFS over the syntax tree."""
    nodes_list = graph["nodes"]
    if node_offset is None:
        node_offset = 0
    name_index: dict[str, str] = graph.setdefault("semantic_name_index", {})
    leaks: list[dict[str, str]] = graph.setdefault("semantic_leaks", [])

    module_scope_by_name: dict[str, Any] = {}
    try:
        for scope in _all_module_scopes(compilation):
            nm = getattr(scope, "name", "") or ""
            if nm and nm not in module_scope_by_name:
                module_scope_by_name[nm] = scope
    except Exception:
        pass

    port_names_by_module: dict[str, set[str]] = {}
    state = {
        "idx": 0,
        "module_stack": [],
        "typedef_stack": [],
        "in_param": 0,
        "in_data": 0,
        "in_port": 0,
        "in_typedef": 0,
        "in_function": 0,
    }

    def _cur_module():
        return state["module_stack"][-1] if state["module_stack"] else (None, "")

    def visit_pass1(node):
        idx = state["idx"]
        state["idx"] += 1
        c = _cls(node)
        gid = nodes_list[node_offset + idx]["id"]
        pushed = None
        popped_module = False

        if c == "ModuleDeclarationSyntax":
            kind_name = str(getattr(node, "kind", "")).rsplit(".", 1)[-1]
            mname = _module_name_of(node)
            state["module_stack"].append((gid, mname))
            popped_module = True
            if kind_name == "PackageDeclaration":
                role_name = "package"
                key_prefix = "package:"
            elif kind_name == "InterfaceDeclaration":
                role_name = "interface"
                key_prefix = "interface:"
            else:
                role_name = "module"
                key_prefix = "module:"
            _mark(nodes_list[node_offset + idx], role=role_name, name=mname, path=mname)
            name_index[key_prefix + mname] = gid
            name_index[mname] = gid
            port_names_by_module.setdefault(mname, set())
        elif c == "ModportItemSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                mport_name = None
                for ch in node:
                    if _is_token(ch) and _token_kind_name(ch) == "Identifier":
                        mport_name = ch.valueText
                        break
                if mport_name is not None:
                    mpath = f"{mname}.{mport_name}"
                    directions: dict[str, str] = {}
                    # Local descendants walk — avoids importing from common
                    # to keep the module slim.
                    def _desc(n):
                        yield n
                        if _is_token(n):
                            return
                        try:
                            kids = list(n)
                        except TypeError:
                            return
                        for x in kids:
                            yield from _desc(x)

                    for d in _desc(node):
                        if _cls(d) != "ModportSimplePortListSyntax":
                            continue
                        dir_tok = None
                        for ch in d:
                            if _is_token(ch) and _token_kind_name(ch) in {
                                "InputKeyword", "OutputKeyword", "InOutKeyword",
                                "RefKeyword",
                            }:
                                dir_tok = ch.valueText
                                break
                        for mnp in _desc(d):
                            if _cls(mnp) != "ModportNamedPortSyntax":
                                continue
                            toks = _identifier_tokens(mnp)
                            if toks and dir_tok is not None:
                                directions[toks[0].valueText] = dir_tok
                    _mark(nodes_list[node_offset + idx], role="modport",
                          name=mport_name, path=mpath, directions=directions)
                    _add_edge(graph, mod_gid, gid, "has_modport")
                    name_index[mpath] = gid
        elif c == "FunctionDeclarationSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                fname = _function_name_of(node)
                if fname:
                    fpath = f"{mname}.{fname}"
                    _mark(nodes_list[node_offset + idx], role="function",
                          name=fname, path=fpath)
                    _add_edge(graph, mod_gid, gid, "has_function")
                    name_index[fpath] = gid
            pushed = "in_function"
        elif c == "PropertyDeclarationSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                pname = _property_name_of(node)
                if pname:
                    ppath = f"{mname}.{pname}"
                    _mark(nodes_list[node_offset + idx], role="property",
                          name=pname, path=ppath)
                    _add_edge(graph, mod_gid, gid, "has_property")
                    name_index[ppath] = gid
        elif c == "SequenceDeclarationSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                sname = _sequence_name_of(node)
                if sname:
                    spath = f"{mname}.{sname}"
                    _mark(nodes_list[node_offset + idx], role="sequence",
                          name=sname, path=spath)
                    _add_edge(graph, mod_gid, gid, "has_sequence")
                    name_index[spath] = gid
        elif c == "TypedefDeclarationSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                tname = _typedef_name_of(node)
                if tname:
                    tpath = f"{mname}.{tname}"
                    _mark(nodes_list[node_offset + idx], role="typedef",
                          name=tname, path=tpath)
                    _add_edge(graph, mod_gid, gid, "has_typedef")
                    name_index[tpath] = gid
                    state["typedef_stack"].append((gid, tname, tpath))
                    pushed = "in_typedef"
        elif c == "ImplicitAnsiPortSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                decl = next((ch for ch in node if _cls(ch) == "DeclaratorSyntax"), None)
                ids = _identifier_tokens(decl) if decl is not None else []
                if ids:
                    pname = ids[0].valueText
                    ppath = f"{mname}.{pname}"
                    _mark(nodes_list[node_offset + idx], role="port", name=pname, path=ppath)
                    _add_edge(graph, mod_gid, gid, "has_port")
                    name_index[ppath] = gid
                    port_names_by_module.setdefault(mname, set()).add(pname)
            pushed = "in_port"
        elif c == "ParameterDeclarationSyntax":
            pushed = "in_param"
        elif c == "DataDeclarationSyntax":
            pushed = "in_data"
        elif c == "DeclaratorSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                ids = _identifier_tokens(node)
                if ids and state["in_port"] == 0:
                    dname = ids[0].valueText
                    dpath = f"{mname}.{dname}"
                    if state["in_typedef"] > 0 and state["typedef_stack"]:
                        td_gid, tname, tpath = state["typedef_stack"][-1]
                        epath = f"{tpath}.{dname}"
                        _mark(nodes_list[node_offset + idx], role="enum_value",
                              name=dname, path=epath)
                        _add_edge(graph, td_gid, gid, "has_enum_value",
                                  name=dname, typedef=tpath)
                        name_index[epath] = gid
                    elif state["in_param"] > 0 and state["in_function"] == 0:
                        _mark(nodes_list[node_offset + idx], role="param", name=dname, path=dpath)
                        _add_edge(graph, mod_gid, gid, "has_param")
                        name_index[dpath] = gid
                    elif (state["in_data"] > 0
                          and state["in_function"] == 0
                          and dname not in port_names_by_module.get(mname, set())):
                        _mark(nodes_list[node_offset + idx], role="net", name=dname, path=dpath)
                        _add_edge(graph, mod_gid, gid, "has_net")
                        name_index[dpath] = gid

        if pushed is not None:
            state[pushed] += 1
        if not _is_token(node):
            try:
                children = list(node)
            except TypeError:
                children = []
            for ch in children:
                visit_pass1(ch)
        if pushed is not None:
            state[pushed] -= 1
        if pushed == "in_typedef" and state["typedef_stack"]:
            state["typedef_stack"].pop()
        if popped_module:
            state["module_stack"].pop()

    if phase in (None, "pass1"):
        visit_pass1(syntax_tree.root)
    if phase == "pass1":
        return

    # Pass 2: rule dispatch via RULE_TABLE.
    state2 = {"idx": 0, "module_stack": [], "in_function": 0,
              "in_generate": 0, "in_bind": 0}

    def _cur_module2():
        return state2["module_stack"][-1] if state2["module_stack"] else (None, "")

    def visit_pass2(node):
        idx = state2["idx"]
        state2["idx"] += 1
        c = _cls(node)
        gid = nodes_list[node_offset + idx]["id"]
        popped = False
        entered_fn = False
        entered_gen = False
        if c == "ModuleDeclarationSyntax":
            mname = _module_name_of(node)
            state2["module_stack"].append((gid, mname))
            popped = True
        if c == "FunctionDeclarationSyntax":
            state2["in_function"] += 1
            entered_fn = True
        if c == "LoopGenerateSyntax":
            entered_gen = True
        entered_bind = False
        if c == "BindDirectiveSyntax":
            entered_bind = True
        mod_gid, mname = _cur_module2()
        scope = module_scope_by_name.get(mname)
        scope_path = mname
        if state2["in_function"] == 0:
            # Look up the active rule by the node's pyslang kind. Only nodes
            # whose kind has an entry in RULE_TABLE are dispatched; the rule
            # function itself decides whether to act (active rules) or no-op
            # (metadata stubs).
            kind = getattr(node, "kind", None)
            fn = RULE_TABLE.get(kind) if kind is not None else None
            if fn is not None and _is_active(fn):
                # Walker-context guards: S6 must not fire inside generate or
                # bind subtrees; S6 also gets module_gid as the parent.
                if fn is rule_s6:
                    if state2["in_generate"] == 0 and state2["in_bind"] == 0:
                        fn(graph, node, gid, nodes_list[node_offset + idx],
                           scope, name_index, leaks, scope_path, module_gid=mod_gid)
                elif fn is rule_s12:
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path, module_gid=mod_gid)
                elif fn is rule_s13:
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path)
                elif fn is rule_s3_or_s8 or getattr(fn, "__rule_id__", None) == "S8":
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path)
                else:
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path)
        if entered_gen:
            state2["in_generate"] += 1
        if entered_bind:
            state2["in_bind"] += 1
        if not _is_token(node):
            try:
                children = list(node)
            except TypeError:
                children = []
            for ch in children:
                visit_pass2(ch)
        if entered_gen:
            state2["in_generate"] -= 1
        if entered_bind:
            state2["in_bind"] -= 1
        if entered_fn:
            state2["in_function"] -= 1
        if popped:
            state2["module_stack"].pop()

    visit_pass2(syntax_tree.root)
    graph["semantic_name_index"] = name_index
