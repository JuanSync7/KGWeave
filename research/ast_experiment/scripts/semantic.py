"""Semantic layer — promote-on-demand projection over the structural backbone.

The structural lift produces one graph node per pyslang syntax node, in DFS
order.  We re-walk the SyntaxTree in the same DFS order, and at every step we
know that the *current* graph node is ``graph['nodes'][dfs_index]``.  We must
do all rule work *inside* the DFS walk because pyslang wrapper objects are
short-lived — saving them across iterations is unsafe (their ``id()`` is
unstable).

Public API:

* ``promote(graph, syntax_tree, compilation)`` — mutate ``graph`` in place.
* ``queryable_nodes(graph)`` — iterator over promoted node dicts.
* ``neighbors(graph, node_id, edge_type=None, direction='out')`` — typed BFS.

Rules:

S1. ModuleDeclarationSyntax → ``has_port``/``has_param``/``has_net``.
S2. ContinuousAssignSyntax → ``drives``(LHS), ``reads``(RHS identifiers).
S3. ProceduralBlockSyntax(always_ff) → ``sensitive_to``/``drives``/``reads``.
S4. IdentifierSelectNameSyntax → ``reads``(base symbol).
S5. SystemNameSyntax(``$clog2``) → ``reads``(argument identifiers).
S7. ParameterValueAssignmentSyntax → ``param_override`` edges from the
    instance node to the child module's ``param`` nodes, with the textual
    resolved expression in the edge payload.
S8. ProceduralBlockSyntax(always_comb) → ``drives``/``reads`` (mirrors S3
    minus ``sensitive_to``; pyslang's ``kind`` is ``AlwaysCombBlock``).
S13. BindDirectiveSyntax → ``bound_into`` edge from the binder module node
    to the target module node, carrying ``instance_name`` and source
    ``scope`` in the edge payload. Resolves binder + target via the shared
    ``semantic_name_index`` so cross-file bind directives wire up correctly.
"""

from __future__ import annotations

from typing import Any, Iterator

# Shim: helpers now live in research.ast_experiment.src.semantic.common.
# Until split-04 completes, this module re-exports them so the rest of
# scripts/semantic.py and external callers (tests/) keep working unchanged.
from research.ast_experiment.src.semantic.common import (  # noqa: F401
    _walk_with_index,
    _descendants,
    _is_token,
    _cls,
    _token_kind_name,
    _identifier_tokens,
    _identifier_names_in,
    _mark,
    _add_edge,
    _has_edge,
    _module_scope,
    _all_module_scopes,
    _scope_path_of,
    _lookup_name,
    _resolve,
    _split_around_eq,
    _lhs_target_name,
    _expression_text,
    _module_name_of,
    _function_name_of,
    _typedef_name_of,
    _enum_value_names,
)


# ---------------------------------------------------------------------------
# Single-pass DFS implementing all rules in one walk.
# ---------------------------------------------------------------------------


def promote(
    graph: dict[str, Any],
    syntax_tree: Any,
    compilation: Any,
    *,
    node_offset: int | None = None,
    phase: str | None = None,
) -> None:
    """Apply S1..S5 (per-module) plus S6 (hierarchical instantiation) in a
    single DFS over the syntax tree, mutating ``graph``.

    Identity keys in ``semantic_name_index`` are hierarchical paths
    (``"<module>.<name>"`` for declarations, ``"<parent>.<inst>"`` for
    instances). Scopes are sourced from the elaborated
    ``InstanceBodySymbol`` chain so the chain matches pyslang's elaboration.

    ``node_offset`` is the starting index into ``graph['nodes']`` for the
    sub-range produced by ``lift`` for this tree. ``None`` means "this tree
    starts at offset 0" (single-tree, back-compat). The name_index is reused
    if it already exists on the graph (so multi-tree callers can resolve
    cross-tree references)."""
    nodes_list = graph["nodes"]
    if node_offset is None:
        node_offset = 0
    name_index: dict[str, str] = graph.setdefault("semantic_name_index", {})
    leaks: list[dict[str, str]] = graph.setdefault("semantic_leaks", [])

    # Build a lookup from module name → elaborated InstanceBodySymbol (where
    # available). Compilation may not have top-instance bodies for every
    # syntactic module (only roots/non-uninstantiated), so we fall back to
    # ``None`` and rely on the syntactic scope path as the keying source.
    module_scope_by_name: dict[str, Any] = {}
    try:
        for scope in _all_module_scopes(compilation):
            # An elaborated InstanceBodySymbol's ``.name`` is the module
            # definition name (e.g. "fifo"), regardless of instance path.
            nm = getattr(scope, "name", "") or ""
            if nm and nm not in module_scope_by_name:
                module_scope_by_name[nm] = scope
    except Exception:
        pass

    # Pass 1 — promote modules + ports/params/nets, build name_index with
    # hierarchical keys. We track the enclosing module name as a string and
    # use it as the scope path.
    port_names_by_module: dict[str, set[str]] = {}

    state = {
        "idx": 0,
        "module_stack": [],          # list[(gid, module_name)]
        "typedef_stack": [],         # list[(gid, typedef_name, typedef_path)]
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
            # Also register the bare name as a top-level lookup so that
            # ``find_by_name('top')`` / ``find_by_name('fifo_pkg')`` /
            # ``find_by_name('fifo_if')`` all resolve.
            name_index[mname] = gid
            port_names_by_module.setdefault(mname, set())
        elif c == "ModportItemSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                # Children: Identifier(name) + AnsiPortListSyntax with
                # ModportSimplePortList[direction, named-ports].
                mport_name = None
                for ch in node:
                    if _is_token(ch) and _token_kind_name(ch) == "Identifier":
                        mport_name = ch.valueText
                        break
                if mport_name is not None:
                    mpath = f"{mname}.{mport_name}"
                    directions: dict[str, str] = {}
                    for d in _descendants(node):
                        if _cls(d) != "ModportSimplePortListSyntax":
                            continue
                        # Find direction keyword + the named-port identifiers.
                        dir_tok = None
                        for ch in d:
                            if _is_token(ch) and _token_kind_name(ch) in {
                                "InputKeyword", "OutputKeyword", "InOutKeyword",
                                "RefKeyword",
                            }:
                                dir_tok = ch.valueText
                                break
                        for mnp in _descendants(d):
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
                        # S9c: enum value declarator inside a typedef-enum.
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

    # Second pass — rules S2..S6 (need name_index complete).
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
            # We dispatch S12 BELOW (the elif chain) before bumping the depth;
            # only the children of the loop must be flagged as in-generate so
            # the syntactic HierarchyInstantiationSyntax under the loop is
            # ignored by S6.
            entered_gen = True
        entered_bind = False
        if c == "BindDirectiveSyntax":
            # Dispatch S13 before bumping in_bind so the rule itself runs;
            # children (the HierarchyInstantiationSyntax under the directive)
            # are flagged in_bind so S6 ignores them.
            entered_bind = True
        mod_gid, mname = _cur_module2()
        scope = module_scope_by_name.get(mname)
        scope_path = mname
        # Inside a function body, suppress S2..S5/S6 — the function's local
        # symbols are not promoted, so reads/drives there would leak.
        if state2["in_function"] == 0:
            if c == "ContinuousAssignSyntax":
                _rule_s2(graph, node, gid, nodes_list[node_offset + idx], scope, name_index, leaks, scope_path)
            elif c == "ProceduralBlockSyntax":
                _rule_s3(graph, node, gid, nodes_list[node_offset + idx], scope, name_index, leaks, scope_path)
            elif c == "IdentifierSelectNameSyntax":
                _rule_s4(graph, node, gid, nodes_list[node_offset + idx], scope, name_index, leaks, scope_path)
            elif c == "InvocationExpressionSyntax":
                _rule_s5(graph, node, gid, nodes_list[node_offset + idx], scope, name_index, leaks, scope_path)
            elif (c == "HierarchyInstantiationSyntax"
                  and state2["in_generate"] == 0
                  and state2["in_bind"] == 0):
                _rule_s6(graph, node, gid, nodes_list[node_offset + idx], scope, name_index, leaks,
                         scope_path, mod_gid)
            elif c == "LoopGenerateSyntax":
                _rule_s12(graph, node, gid, nodes_list[node_offset + idx], scope, name_index, leaks,
                          scope_path, mod_gid)
            elif c == "BindDirectiveSyntax":
                _rule_s13(graph, node, gid, nodes_list[node_offset + idx], name_index, leaks)
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


# ---------------------------------------------------------------------------
# Per-rule helpers.
# ---------------------------------------------------------------------------


def _rule_s2(graph, node, gid, gnode, scope, name_index, leaks, scope_path=""):
    # ContinuousAssign wraps a SeparatedList of assignment expressions.
    # Find the first BinaryExpressionSyntax(AssignmentExpression) descendant.
    assign_expr = None
    for d in _descendants(node):
        if _cls(d) == "BinaryExpressionSyntax" and "AssignmentExpression" in str(getattr(d, "kind", "")):
            assign_expr = d
            break
    if assign_expr is None:
        return
    lhs, rhs = _split_around_eq(assign_expr)
    if lhs is None or rhs is None:
        return
    lhs_name = _lhs_target_name(lhs)
    _mark(gnode, role="continuous_assign", lhs=lhs_name)
    if lhs_name:
        tgt = _resolve(lhs_name, scope=scope, name_index=name_index, leaks=leaks,
                       context=f"continuous_assign.lhs[{gid}]", scope_path=scope_path)
        if tgt is not None:
            _add_edge(graph, gid, tgt, "drives")
    seen_reads: set[str] = set()
    for rname in _identifier_names_in(rhs):
        if rname == lhs_name or rname in seen_reads:
            continue
        seen_reads.add(rname)
        src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                       context=f"continuous_assign.rhs[{gid}]", scope_path=scope_path)
        if src is not None:
            _add_edge(graph, gid, src, "reads")


def _rule_s3(graph, node, gid, gnode, scope, name_index, leaks, scope_path=""):
    kw = next((c for c in node if _is_token(c)), None)
    if kw is None:
        return
    kw_text = kw.valueText
    if kw_text == "always_ff":
        role = "always_ff"
        do_sensitivity = True
    elif kw_text == "always_comb":
        role = "always_comb"
        do_sensitivity = False
    else:
        return
    _mark(gnode, role=role)

    # Pre-pass: detect function invocations in this block. For each
    # InvocationExpressionSyntax whose callee identifier resolves to a
    # ``function``-role node in name_index (same module scope), emit a
    # ``calls`` edge and remember the function's bare name so the reads-pass
    # does not emit a stray ``reads`` edge for it.
    function_call_names: set[str] = set()
    # `node` is the ProceduralBlockSyntax — defer descendants walk to a local fn.
    def _descendants_local(n):
        yield n
        if _is_token(n):
            return
        try:
            kids = list(n)
        except TypeError:
            return
        for c in kids:
            yield from _descendants_local(c)

    for d in _descendants_local(node):
        if _cls(d) != "InvocationExpressionSyntax":
            continue
        callee = next((c for c in d if not _is_token(c)), None)
        if callee is None or _cls(callee) != "IdentifierNameSyntax":
            continue
        toks = _identifier_tokens(callee)
        if not toks:
            continue
        fn_name = toks[0].valueText
        # Resolve to a function-role node in the current module scope.
        fpath = f"{scope_path}.{fn_name}" if scope_path else fn_name
        fn_id = name_index.get(fpath)
        if fn_id is None:
            continue
        # Lookup the node to confirm role=function.
        fn_node = next((nn for nn in graph["nodes"] if nn["id"] == fn_id), None)
        if fn_node is None or fn_node.get("semantic", {}).get("role") != "function":
            continue
        if not _has_edge(graph, gid, fn_id, "calls"):
            _add_edge(graph, gid, fn_id, "calls")
        function_call_names.add(fn_name)

    # Helper: collect all descendant syntax nodes in a list (DFS), so we can
    # introspect them without re-walking from the outer DFS.
    def descendants(n):
        yield n
        if _is_token(n):
            return
        try:
            children = list(n)
        except TypeError:
            return
        for c in children:
            yield from descendants(c)

    # Sensitivity: SignalEventExpressionSyntax (only for always_ff).
    if do_sensitivity:
        for d in descendants(node):
            if _cls(d) != "SignalEventExpressionSyntax":
                continue
            edge = None
            for t in descendants(d):
                if _is_token(t) and t.valueText in {"posedge", "negedge", "edge"}:
                    edge = t.valueText
                    break
            ids = _identifier_tokens(d)
            if not ids:
                continue
            sig = ids[0].valueText
            tgt = _resolve(sig, scope=scope, name_index=name_index, leaks=leaks,
                           context=f"{role}.sensitive_to[{gid}]", scope_path=scope_path)
            if tgt is not None:
                _add_edge(graph, gid, tgt, "sensitive_to", edge=edge)

    # Drives / reads from assignment-form BinaryExpressionSyntax.
    for d in descendants(node):
        if _cls(d) != "BinaryExpressionSyntax":
            continue
        op = next((c for c in d if _is_token(c)), None)
        if op is None:
            continue
        if _token_kind_name(op) not in {"LessThanEquals", "Equals"}:
            continue
        lhs, rhs = _split_around_eq(d)
        if lhs is None or rhs is None:
            continue
        lhs_name = _lhs_target_name(lhs)
        if lhs_name:
            tgt = _resolve(lhs_name, scope=scope, name_index=name_index, leaks=leaks,
                           context=f"{role}.drives[{gid}]", scope_path=scope_path)
            if tgt is not None and not _has_edge(graph, gid, tgt, "drives"):
                _add_edge(graph, gid, tgt, "drives")
        for rname in _identifier_names_in(rhs):
            if rname == lhs_name or rname in function_call_names:
                continue
            src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                           context=f"{role}.reads[{gid}]", scope_path=scope_path)
            if src is not None and not _has_edge(graph, gid, src, "reads"):
                _add_edge(graph, gid, src, "reads")

    # Reads from predicates and case heads.
    for d in descendants(node):
        c = _cls(d)
        if c == "ConditionalPredicateSyntax":
            for rname in _identifier_names_in(d):
                if rname in function_call_names:
                    continue
                src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                               context=f"{role}.reads.predicate[{gid}]", scope_path=scope_path)
                if src is not None and not _has_edge(graph, gid, src, "reads"):
                    _add_edge(graph, gid, src, "reads")
        elif c == "CaseStatementSyntax":
            head = next((ch for ch in d if not _is_token(ch)), None)
            if head is None:
                continue
            for rname in _identifier_names_in(head):
                if rname in function_call_names:
                    continue
                src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                               context=f"{role}.reads.case_head[{gid}]", scope_path=scope_path)
                if src is not None and not _has_edge(graph, gid, src, "reads"):
                    _add_edge(graph, gid, src, "reads")


def _rule_s12(graph, node, gid, gnode, scope, name_index, leaks,
              scope_path="", module_gid=None):
    """S12: LoopGenerateSyntax + elaborated GenerateBlockSyntax instances.

    Promotes the LoopGenerateSyntax as a queryable ``generate_loop`` node and
    asks the elaborated module scope for the matching ``GenerateBlockArraySymbol``
    (matched by label). Each entry of the array becomes a synthetic
    ``generate_block`` node carrying the elaborated hierarchical path; every
    InstanceSymbol under that block is promoted as a synthetic instance node
    and wired with ``of_module`` / ``instantiates`` edges so
    ``instances_of('fifo')`` lists the elaborated copies alongside the
    syntactically-named instances.
    """
    # Find the label inside the LoopGenerateSyntax's GenerateBlockSyntax.
    label = None
    for d in _descendants(node):
        if _cls(d) != "GenerateBlockSyntax":
            continue
        # NamedBlockClauseSyntax holds ``: <label>``; otherwise the block has
        # no label and the elaborated array's name is auto-synthesized.
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
        # Best-effort path so inv6 stays clean even without elaboration data.
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
    # Containment edge from the enclosing module to this generate_loop so
    # inv1 (containment BFS) reaches the loop + every block + every generated
    # instance.
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
        # Tie the synthetic block under the syntactic generate_loop node so
        # invariants can walk a containment chain ``module → loop → block``.
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


def _rule_s4(graph, node, gid, gnode, scope, name_index, leaks, scope_path=""):
    ids = _identifier_tokens(node)
    if not ids:
        return
    base = ids[0].valueText
    _mark(gnode, role="identifier_select", base=base)
    tgt = _resolve(base, scope=scope, name_index=name_index, leaks=leaks,
                   context=f"identifier_select.base[{gid}]", scope_path=scope_path)
    if tgt is not None:
        _add_edge(graph, gid, tgt, "reads")


def _rule_s5(graph, node, gid, gnode, scope, name_index, leaks, scope_path=""):
    callee = next((c for c in node if not _is_token(c)), None)
    if callee is None or _cls(callee) != "SystemNameSyntax":
        return
    # System names use TokenKind.SystemIdentifier, not Identifier.
    sysname = None
    for ch in callee:
        if _is_token(ch) and _token_kind_name(ch) == "SystemIdentifier":
            sysname = ch.valueText
            break
    if sysname is None:
        return
    _mark(gnode, role="system_call", name=sysname)
    arglist = next((c for c in node if _cls(c) == "ArgumentListSyntax"), None)
    if arglist is None:
        return
    seen: set[str] = set()
    for rname in _identifier_names_in(arglist):
        if rname in seen:
            continue
        seen.add(rname)
        tgt = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                       context=f"system_call.arg[{gid}]", scope_path=scope_path)
        if tgt is not None:
            _add_edge(graph, gid, tgt, "reads")


# ---------------------------------------------------------------------------
# Public queries.
# ---------------------------------------------------------------------------


def _rule_s13(graph, node, gid, gnode, name_index, leaks):
    """S13: BindDirectiveSyntax → ``bound_into`` edge.

    Grammar (per pyslang AST dump)::

        BindDirective
          <attributes>          # SyntaxList, usually empty
          'bind' keyword
          IdentifierNameSyntax  # target module being bound INTO (e.g. fifo)
          HierarchyInstantiationSyntax
            <attributes>
            Identifier          # binder module name (e.g. fifo_asserts)
            HierarchicalInstance
              InstanceName      # bind instance name (e.g. u_asserts)
              '(' ... ')'
          ';'

    The rule resolves both module names via the shared ``name_index`` (built
    in pass1, populated cross-file by ``build_kg``'s two-phase ordering) and
    emits exactly one ``bound_into`` edge per bind directive, anchored at
    the existing module-definition nodes — no new structural nodes are
    promoted. Payload: ``{instance_name, scope}`` where ``scope`` is the
    id-prefix of the BindDirective gid (the source-file stem).
    """
    # Children of BindDirectiveSyntax in order: SyntaxList, 'bind' keyword,
    # IdentifierNameSyntax (target), HierarchyInstantiationSyntax (binder).
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
    # Binder module type = first Identifier token child of the
    # HierarchyInstantiationSyntax (same shape S6 uses).
    binder_name: str | None = None
    inst_name: str | None = None
    for ch in hier_inst:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier" and binder_name is None:
            binder_name = ch.valueText
            break
    # InstanceName under HierarchicalInstance.
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
    # Source-file scope = the id-prefix of the BindDirective gid (e.g.
    # ``fifo_asserts:n0001.BindDirectiveSyntax`` → ``fifo_asserts``).
    scope = gid.split(":", 1)[0] if ":" in gid else ""
    if not _has_edge(graph, binder_gid, target_gid, "bound_into"):
        _add_edge(graph, binder_gid, target_gid, "bound_into",
                  instance_name=inst_name or "", scope=scope)


def _rule_s6(graph, node, gid, gnode, scope, name_index, leaks,
             scope_path="", module_gid=None):
    """S6: HierarchyInstantiationSyntax → instance + of_module + connects.

    Promotes each hierarchical instance to an ``instance``-role node anchored
    at ``<scope_path>.<inst_name>``. Edges:
      * ``<scope_path>.<inst>``   --of_module-->  ``module:<type>``
      * ``<scope_path>``          --instantiates-->  ``<scope_path>.<inst>``
      * for each named port connection: ``<scope_path>.<connected_net>``
        --connects-->  ``<scope_path>.<inst>.<port>``
    """
    # The module-type identifier appears as a direct Identifier Token child
    # of HierarchyInstantiationSyntax (e.g. ``fifo`` in ``fifo u_fifo(...)``).
    # Fall back to scanning non-token children for an embedded identifier.
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
    # S7: extract ParameterValueAssignmentSyntax (param override block), if any.
    # The block is a direct child of the HierarchyInstantiationSyntax and
    # applies to every HierarchicalInstance under this declaration.
    overrides: list[tuple[str, str]] = []  # ordered list of (param_name, value_text)
    pva = next((c for c in node if _cls(c) == "ParameterValueAssignmentSyntax"), None)
    if pva is not None:
        # Named overrides: NamedParamAssignmentSyntax(.NAME(EXPR)) descendants.
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
                    # First non-token child after '(' is the expression.
                    try:
                        sub_kids = list(ch)
                    except TypeError:
                        sub_kids = []
                    if sub_kids or _identifier_tokens(ch):
                        expr_text = _expression_text(ch)
                        break
            if pname is not None and expr_text is not None:
                overrides.append((pname, expr_text))
        # Positional overrides (OrderedParamAssignmentSyntax) — defer until a
        # corpus exercises them; current corpus uses only named overrides.
        if not named_seen:
            pass
    # Find every HierarchicalInstanceSyntax under this declaration.
    for d in _descendants(node):
        if _cls(d) != "HierarchicalInstanceSyntax":
            continue
        # InstanceNameSyntax → first identifier token.
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
        # Locate the corresponding graph node for this HierarchicalInstance.
        # The promote() walker assigned IDs in DFS order matching nodes_list;
        # we don't have it here, so re-discover by matching id-in-edges.
        # Simpler: store on the HierarchyInstantiationSyntax node itself, and
        # also create a virtual instance entry in the name_index.
        # We anchor the instance node at the HierarchicalInstanceSyntax gid.
        # Find gid by walking edges to find the dst whose ordinal child matches.
        hi_gid = _gid_for_subtree(graph, gid, "HierarchicalInstanceSyntax",
                                   target_inst=inst_name)
        if hi_gid is None:
            continue
        # Mark the instance node.
        idx = _node_index_by_id(graph, hi_gid)
        if idx is None:
            continue
        _mark(graph["nodes"][idx], role="instance", name=inst_name,
              path=inst_path, of_module=type_name)
        name_index[inst_path] = hi_gid
        # Edges: parent module --instantiates--> instance ; instance --of_module--> module
        if module_gid is not None and not _has_edge(graph, module_gid, hi_gid, "instantiates"):
            _add_edge(graph, module_gid, hi_gid, "instantiates")
        if type_node_id is not None and not _has_edge(graph, hi_gid, type_node_id, "of_module"):
            _add_edge(graph, hi_gid, type_node_id, "of_module")
        # S7: param_override edges from the instance node to the child module's
        # param nodes. The override block applies identically to every instance
        # in this HierarchyInstantiationSyntax declaration.
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
        # Port connections: NamedPortConnectionSyntax under this instance.
        for npc in _descendants(d):
            if _cls(npc) != "NamedPortConnectionSyntax":
                continue
            # Children: SyntaxNode(empty?), '.', Identifier(portName), '(', expr, ')'.
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
                    # Skip empty wrapper nodes.
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
            # Resolve port to its declared port in the child module.
            child_port_id = name_index.get(f"{type_name}.{port_name}")
            if child_port_id is not None:
                # Anchor the port-connection through a path key for queryability.
                name_index[port_path] = child_port_id
            # RHS expression: collect identifier tokens from the connection
            # expression only (post the port-name token).
            rhs_names: list[str] = []
            if expr_node is not None:
                for tok in _identifier_tokens(expr_node):
                    rhs_names.append(tok.valueText)
            for rname in rhs_names:
                # Resolve in parent scope.
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


def _gid_for_subtree(graph, parent_gid, target_class, target_inst=None):
    """Find a descendant graph-node id of ``parent_gid`` whose type matches
    ``target_class``. If ``target_inst`` is given, prefer the descendant that
    contains an Identifier token with that valueText (the InstanceName)."""
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    children_by_src: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e.get("type") != "child":
            continue
        children_by_src.setdefault(e["src"], []).append(e["dst"])
    # DFS within parent subtree
    stack = [parent_gid]
    matches: list[str] = []
    while stack:
        cur = stack.pop()
        n = nodes_by_id.get(cur)
        if n is None:
            continue
        if n["type"] == target_class:
            matches.append(cur)
        # children — order doesn't matter for matching but we sort by edge index
        kids = children_by_src.get(cur, [])
        stack.extend(reversed(kids))
    if not matches:
        return None
    if target_inst is None:
        return matches[0]
    # Choose the match whose subtree contains an Identifier token with valueText==target_inst.
    for m in matches:
        # collect descendant tokens
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


def queryable_nodes(graph: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for n in graph["nodes"]:
        if n.get("queryable"):
            yield n


def neighbors(
    graph: dict[str, Any],
    node_id: str,
    edge_type: str | None = None,
    direction: str = "out",
) -> list[dict[str, Any]]:
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[dict[str, Any]] = []
    for e in graph["edges"]:
        if edge_type is not None and e["type"] != edge_type:
            continue
        if direction == "out" and e["src"] == node_id:
            out.append(by_id[e["dst"]])
        elif direction == "in" and e["dst"] == node_id:
            out.append(by_id[e["src"]])
    return out


def find_by_name(graph: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Look up a promoted node by hierarchical path or bare leaf name.

    Accepts either a full path (``"fifo.count"``, ``"top.u_fifo"``) or a bare
    leaf name (``"count"``). Bare-name lookup is satisfied only if exactly one
    promoted entry matches — ambiguous bare-name queries return ``None``.
    """
    idx = graph.get("semantic_name_index", {})
    nid = idx.get(name)
    if nid is None:
        # Bare-name fallback.
        suffix = "." + name
        candidates = [v for k, v in idx.items() if k == name or k.endswith(suffix)]
        if len(candidates) == 1:
            nid = candidates[0]
    if nid is None:
        return None
    by_id = {n["id"]: n for n in graph["nodes"]}
    return by_id[nid]


def find_drivers(graph: dict[str, Any], name: str) -> list[dict[str, Any]]:
    target = find_by_name(graph, name)
    if target is None:
        return []
    return neighbors(graph, target["id"], edge_type="drives", direction="in")


def reads_of(graph: dict[str, Any], name: str) -> list[dict[str, Any]]:
    target = find_by_name(graph, name)
    if target is None:
        return []
    return neighbors(graph, target["id"], edge_type="reads", direction="in")


def graph_query(graph: dict[str, Any], pattern: dict[str, Any]) -> list[Any]:
    """Tiny typed pattern walker over the graph — the 20% escape hatch.

    ``pattern`` shape::

        {
            "match": {"type": "...", "name": "...", "role": "...", "path": "..."},
            "follow": [
                {"edge": "drives|reads|connects|...",
                 "direction": "out|in",
                 "filter": {"role": "...", "type": "...", "name": "...",
                            "payload": {"<key>": "<value>"},
                            "payload_edge": {"<edge-payload-key>": "<value>"}}},
                ...
            ],
            "return": "node" | "name" | "id" | "path",
        }

    Semantics: ``match`` selects the start frontier; each ``follow`` step is one
    typed BFS hop with optional node and edge-payload filters; the final frontier
    is projected via ``return`` (default ``"node"``). All matching is
    exact-equality over typed attributes — no regex, no substring scans.
    """
    nodes = graph["nodes"]
    by_id = {n["id"]: n for n in nodes}

    def _node_matches(n: dict[str, Any], pred: dict[str, Any]) -> bool:
        for k, v in pred.items():
            if k == "type":
                if n.get("type") != v:
                    return False
            elif k in {"role", "name", "path"}:
                if n.get("semantic", {}).get(k) != v:
                    return False
            elif k == "payload":
                payload = n.get("payload", {})
                if not isinstance(payload, dict):
                    return False
                for pk, pv in v.items():
                    if payload.get(pk) != pv:
                        return False
            elif k == "queryable":
                if bool(n.get("queryable")) != bool(v):
                    return False
            elif k == "payload_edge":
                # Edge-payload predicates are not node-level; ignore here.
                continue
            else:
                if n.get(k) != v:
                    return False
        return True

    def _edge_payload_matches(edge: dict[str, Any], pred: dict[str, Any]) -> bool:
        ep = edge.get("payload", {}) or {}
        for k, v in pred.items():
            if ep.get(k) != v:
                return False
        return True

    match_pred = pattern.get("match", {}) or {}
    frontier: list[str] = [n["id"] for n in nodes if _node_matches(n, match_pred)]

    for step in pattern.get("follow", []) or []:
        edge_type = step.get("edge")
        direction = step.get("direction", "out")
        node_filter_raw = step.get("filter", {}) or {}
        edge_payload_pred = node_filter_raw.get("payload_edge") if isinstance(node_filter_raw, dict) else None
        node_filter = {k: v for k, v in node_filter_raw.items() if k != "payload_edge"}
        next_frontier: list[str] = []
        frontier_set = set(frontier)
        for e in graph["edges"]:
            if edge_type is not None and e["type"] != edge_type:
                continue
            if edge_payload_pred is not None and not _edge_payload_matches(e, edge_payload_pred):
                continue
            if direction == "out":
                if e["src"] not in frontier_set:
                    continue
                dst = by_id.get(e["dst"])
                if dst is None:
                    continue
                if _node_matches(dst, node_filter):
                    next_frontier.append(dst["id"])
            elif direction == "in":
                if e["dst"] not in frontier_set:
                    continue
                src = by_id.get(e["src"])
                if src is None:
                    continue
                if _node_matches(src, node_filter):
                    next_frontier.append(src["id"])
        frontier = next_frontier

    projection = pattern.get("return", "node")
    if projection == "id":
        return sorted(set(frontier))
    if projection == "name":
        return sorted({by_id[i].get("semantic", {}).get("name")
                       for i in frontier
                       if by_id[i].get("semantic", {}).get("name") is not None})
    if projection == "path":
        return sorted({by_id[i].get("semantic", {}).get("path")
                       for i in frontier
                       if by_id[i].get("semantic", {}).get("path") is not None})
    seen_ids: set[str] = set()
    out: list[dict[str, Any]] = []
    for i in frontier:
        if i in seen_ids:
            continue
        seen_ids.add(i)
        out.append(by_id[i])
    return out


def instances_of(graph: dict[str, Any], module_name: str) -> list[str]:
    """Return every instance path whose ``of_module`` points at ``module_name``.

    Pure typed-edge traversal: walks ``of_module`` edges in-reverse from the
    module-definition node, projecting each source instance's ``semantic.path``.
    """
    by_id = {n["id"]: n for n in graph["nodes"]}
    idx = graph.get("semantic_name_index", {})
    mod_id = idx.get("module:" + module_name) or idx.get(module_name)
    if mod_id is None:
        return []
    out: list[str] = []
    for e in graph["edges"]:
        if e["type"] != "of_module" or e["dst"] != mod_id:
            continue
        src = by_id.get(e["src"])
        if src is None:
            continue
        path = src.get("semantic", {}).get("path")
        if path:
            out.append(path)
    return sorted(out)


def port_connections(graph: dict[str, Any], instance_path: str) -> list[dict[str, Any]]:
    """Return the named port-connection map for an instance.

    Each entry is ``{"port": <child-port-name>, "src_path": <parent-net-path>}``
    derived from every ``connects`` edge whose payload ``instance`` matches
    ``instance_path``. Edge payload is the sole source of truth — no name-string
    parsing is involved.
    """
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[dict[str, Any]] = []
    for e in graph["edges"]:
        if e["type"] != "connects":
            continue
        if e["payload"].get("instance") != instance_path:
            continue
        src = by_id.get(e["src"])
        if src is None:
            continue
        src_path = src.get("semantic", {}).get("path") or src.get("semantic", {}).get("name")
        out.append({"port": e["payload"].get("port"), "src_path": src_path})
    return out


def modports_of(graph: dict[str, Any], interface_name: str) -> list[str]:
    """Return the sorted list of modport names declared in an interface."""
    iface = find_by_name(graph, interface_name)
    if iface is None:
        return []
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[str] = []
    for e in graph["edges"]:
        if e["type"] != "has_modport" or e["src"] != iface["id"]:
            continue
        dst = by_id.get(e["dst"])
        if dst is None:
            continue
        nm = dst.get("semantic", {}).get("name")
        if nm:
            out.append(nm)
    return sorted(out)


def package_of(graph: dict[str, Any], typedef_path: str) -> str | None:
    """Return the package (or module) that owns a typedef, via the reverse
    ``has_typedef`` edge. Returns ``None`` if the typedef has no enclosing
    container in the graph."""
    td = find_by_name(graph, typedef_path)
    if td is None:
        return None
    by_id = {n["id"]: n for n in graph["nodes"]}
    for e in graph["edges"]:
        if e["type"] != "has_typedef" or e["dst"] != td["id"]:
            continue
        owner = by_id.get(e["src"])
        if owner is None:
            continue
        return owner.get("semantic", {}).get("name")
    return None


def param_overrides(graph: dict[str, Any], instance_path: str) -> dict[str, str]:
    """Return the resolved param-override map for an instance.

    Walks outgoing ``param_override`` edges from the instance node, projecting
    each edge's payload as ``{name: value}``. Returns an empty dict for
    instances with no overrides. Pure typed-edge projection — no syntax
    re-walking, no regex.
    """
    inst = find_by_name(graph, instance_path)
    if inst is None:
        return {}
    out: dict[str, str] = {}
    for e in graph["edges"]:
        if e["type"] != "param_override" or e["src"] != inst["id"]:
            continue
        name = e["payload"].get("name")
        value = e["payload"].get("value")
        if name is not None:
            out[name] = value
    return out


def sensitivity_of(graph: dict[str, Any], always_block_id: str) -> list[dict[str, Any]]:
    """Return ``[{"signal": <net/port path>, "edge": <posedge|negedge|edge>}, …]``
    from outgoing ``sensitive_to`` edges of an ``always_*`` node."""
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[dict[str, Any]] = []
    for e in graph["edges"]:
        if e["type"] != "sensitive_to" or e["src"] != always_block_id:
            continue
        dst = by_id.get(e["dst"])
        if dst is None:
            continue
        sig = dst.get("semantic", {}).get("path") or dst.get("semantic", {}).get("name")
        out.append({"signal": sig, "edge": e["payload"].get("edge")})
    return out


# ---------------------------------------------------------------------------
# Structural-payload helpers used by width_of / default_value_of.
# These read only via typed ``child`` edges and Token rawText — no regex,
# no substring scans over identifiers.
# ---------------------------------------------------------------------------


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
    """Reconstruct the raw token text under ``nid`` from typed Token payloads.

    The walk follows ordered ``child`` edges only. Token leading trivia is
    omitted by default so width / default-value strings come out clean
    (``[WIDTH-1:0]`` not ``"  [WIDTH-1:0]"``).
    """
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
    """First direct child whose ``type`` (class-name) is in ``kinds``."""
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
    """Return the structural width of a net or port.

    Result shape::

        {"packed_dim": "[WIDTH-1:0]" | None,
         "unpacked_dim": "[DEPTH]"   | None,
         "data_type":   "logic"      | None}

    Reads only via typed ``child`` edges + the lifted Token rawText payload.
    """
    target = find_by_name(graph, net_or_port_path)
    if target is None:
        return {"packed_dim": None, "unpacked_dim": None, "data_type": None}
    by_id = {n["id"]: n for n in graph["nodes"]}
    role = target.get("semantic", {}).get("role")
    nid = target["id"]

    if role == "port":
        # Port node is ImplicitAnsiPortSyntax. Children: SyntaxList?,
        # VariablePortHeaderSyntax (contains data-type + packed dim),
        # DeclaratorSyntax (contains identifier + optional unpacked dim list).
        header = _first_child_of_kind(graph, nid, {"VariablePortHeaderSyntax"})
        decl = _first_child_of_kind(graph, nid, {"DeclaratorSyntax"})
    else:
        # Net / param: target IS the DeclaratorSyntax. The data-type sits on
        # the enclosing DataDeclarationSyntax (grandparent: declarator → SepList → DataDecl).
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
        # data_type token: first type-keyword Token reachable under the header.
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
        # packed dim — concatenate every VariableDimensionSyntax found inside header.
        dims = _descendants_of_kind(graph, header, {"VariableDimensionSyntax"})
        if dims:
            # Drop leading whitespace trivia by passing include_leading_trivia=False
            packed = "".join(_text_of_subtree(graph, d) for d in dims).lstrip()

    unpacked = None
    if decl is not None:
        # Unpacked dim sits AFTER the identifier in the DeclaratorSyntax children.
        # The dims are siblings inside the inner SyntaxList child.
        for c in _children_of(graph, decl):
            cn = by_id[c]
            if cn["type"] == "SyntaxNode" and "SyntaxList" in cn.get("kind", ""):
                dims = _descendants_of_kind(graph, c, {"VariableDimensionSyntax"})
                if dims:
                    unpacked = "".join(_text_of_subtree(graph, d) for d in dims).lstrip()
                    break

    return {"packed_dim": packed, "unpacked_dim": unpacked, "data_type": data_type}


def default_value_of(graph: dict[str, Any], param_path: str) -> str | None:
    """Return the textual default expression of a parameter, or ``None``.

    The target node is the parameter's ``DeclaratorSyntax``; the default sits in
    its ``EqualsValueClauseSyntax`` child (``= <expr>``). We project the
    expression text (right of ``=``) via typed child edges.
    """
    target = find_by_name(graph, param_path)
    if target is None:
        return None
    by_id = {n["id"]: n for n in graph["nodes"]}
    nid = target["id"]
    eq_clause = _first_child_of_kind(graph, nid, {"EqualsValueClauseSyntax"})
    if eq_clause is None:
        return None
    # The expression is the first non-token, non-empty child after the '=' token.
    saw_eq = False
    for c in _children_of(graph, eq_clause):
        cn = by_id[c]
        if cn.get("is_token") and cn.get("kind", "").endswith(".Equals"):
            saw_eq = True
            continue
        if not saw_eq:
            continue
        # Project this expression's text.
        text = _text_of_subtree(graph, c).strip()
        return text if text else None
    return None


def forward_cone(graph: dict[str, Any], name: str) -> set[str]:
    """Forward reachability: from ``name``, follow what *it drives* (via
    ``read_by`` semantics — i.e. nodes that read this signal, then what they
    drive). Crosses hierarchy outward through outgoing ``connects`` edges
    (child-port → parent-net is one direction; we also follow parent-net →
    child-port when standing on a parent net).

    Symmetric counterpart to :func:`cone_of_influence`.
    """
    target = find_by_name(graph, name)
    if target is None:
        return set()
    seen: set[str] = set()
    frontier = [target["id"]]
    while frontier:
        nxt: list[str] = []
        for nid in frontier:
            if nid in seen:
                continue
            seen.add(nid)
            # Nodes that READ this signal (incoming readers).
            for reader in neighbors(graph, nid, edge_type="reads", direction="in"):
                if reader["id"] not in seen:
                    nxt.append(reader["id"])
                # Whatever those readers DRIVE (outgoing).
                for d in neighbors(graph, reader["id"], edge_type="drives", direction="out"):
                    if d["id"] not in seen:
                        nxt.append(d["id"])
            # Cross hierarchy outward via connects edges.
            for connected in neighbors(graph, nid, edge_type="connects", direction="out"):
                if connected["id"] not in seen:
                    nxt.append(connected["id"])
            for connected in neighbors(graph, nid, edge_type="connects", direction="in"):
                # parent-net → child-port: only follow if we are the source.
                if connected["id"] not in seen:
                    nxt.append(connected["id"])
        frontier = nxt
    return seen


def cone_of_influence(graph: dict[str, Any], name: str) -> set[str]:
    """Backward reachability: from ``name``, follow drivers; from drivers,
    follow what they read; cross hierarchy boundaries via incoming ``connects``
    edges (parent-net → child-port). Returns the set of visited node ids."""
    target = find_by_name(graph, name)
    if target is None:
        return set()
    seen: set[str] = set()
    frontier = [target["id"]]
    while frontier:
        nxt: list[str] = []
        for nid in frontier:
            if nid in seen:
                continue
            seen.add(nid)
            for driver in neighbors(graph, nid, edge_type="drives", direction="in"):
                if driver["id"] not in seen:
                    nxt.append(driver["id"])
                for r in neighbors(graph, driver["id"], edge_type="reads", direction="out"):
                    if r["id"] not in seen:
                        nxt.append(r["id"])
            # Cross hierarchy: a parent net `connects` to this node (child port).
            for parent in neighbors(graph, nid, edge_type="connects", direction="in"):
                if parent["id"] not in seen:
                    nxt.append(parent["id"])
        frontier = nxt
    return seen
