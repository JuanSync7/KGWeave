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
"""

from __future__ import annotations

from typing import Any, Iterator


# ---------------------------------------------------------------------------
# Walk primitives.
# ---------------------------------------------------------------------------


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


def _is_token(node: Any) -> bool:
    return type(node).__name__ == "Token"


def _cls(node: Any) -> str:
    return type(node).__name__


def _token_kind_name(tok: Any) -> str:
    return str(tok.kind).rsplit(".", 1)[-1]


def _identifier_tokens(node: Any) -> list[Any]:
    out: list[Any] = []
    if _is_token(node):
        if _token_kind_name(node) == "Identifier":
            out.append(node)
        return out
    try:
        children = list(node)
    except TypeError:
        return out
    for c in children:
        out.extend(_identifier_tokens(c))
    return out


def _identifier_names_in(node: Any) -> list[str]:
    return [t.valueText for t in _identifier_tokens(node)]


# ---------------------------------------------------------------------------
# Graph helpers.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Symbol resolution via Compilation, with a name-string fallback escape hatch.
# ---------------------------------------------------------------------------


def _module_scope(compilation: Any) -> Any:
    """Legacy: return the FIRST top instance body. Retained for back-compat;
    multi-module callers should iterate ``_all_module_scopes``."""
    top = list(compilation.getRoot().topInstances)
    if not top:
        return None
    return top[0].body


def _all_module_scopes(compilation: Any) -> list[Any]:
    """Return every elaborated ``InstanceBodySymbol`` in the compilation.

    Walks every top instance and recursively descends through child instance
    symbols. The path of each scope is reconstructed by
    ``_scope_path_of(scope)``.
    """
    out: list[Any] = []
    seen: set[int] = set()

    def visit(scope: Any) -> None:
        if scope is None:
            return
        key = id(scope)
        if key in seen:
            return
        seen.add(key)
        out.append(scope)

    def descend(body: Any) -> None:
        if body is None:
            return
        visit(body)
        # InstanceBodySymbol exposes its child symbols via iteration; descend
        # through any InstanceSymbol children to reach nested instance bodies.
        try:
            members = list(body)
        except TypeError:
            members = []
        for sym in members:
            sub_body = getattr(sym, "body", None)
            if sub_body is not None and id(sub_body) not in seen:
                descend(sub_body)

    for inst in compilation.getRoot().topInstances:
        body = getattr(inst, "body", None)
        descend(body)
    return out


def _scope_path_of(scope: Any) -> str:
    """Hierarchical path for an elaborated scope.

    For a top-level module body this is just the module name (e.g. ``"fifo"``
    or ``"top"``). For a nested instance body it would be the dotted chain
    ``parent.inst_name.child_inst...`` — pyslang's ``hierarchicalPath`` covers
    this when available; otherwise fall back to the scope's ``name``.
    """
    if scope is None:
        return ""
    # Prefer the symbol's elaborated hierarchical path if exposed.
    for attr in ("hierarchicalPath",):
        try:
            v = getattr(scope, attr, None)
            if isinstance(v, str) and v:
                # pyslang sometimes uses ``$root.top`` — strip the leading marker.
                if v.startswith("$root."):
                    return v[len("$root."):]
                return v
        except Exception:
            pass
    try:
        nm = getattr(scope, "name", None)
        if isinstance(nm, str) and nm:
            return nm
    except Exception:
        pass
    return ""


def _lookup_name(scope: Any, name: str) -> Any | None:
    if scope is None:
        return None
    try:
        sym = scope.find(name)
        if sym is not None:
            return sym
    except Exception:
        pass
    try:
        return scope.lookupName(name)
    except Exception:
        return None


def _resolve(
    name: str,
    *,
    scope: Any,
    name_index: dict[str, str],
    leaks: list[dict[str, str]],
    context: str,
    scope_path: str = "",
) -> str | None:
    """Resolve ``name`` to a graph id; record a leak if we fall back.

    Keys in ``name_index`` are hierarchical: ``"<scope_path>.<name>"``. If a
    bare ``name`` is passed we first expand it against ``scope_path``.
    """
    sym = _lookup_name(scope, name)
    key = f"{scope_path}.{name}" if scope_path else name
    nid = name_index.get(key)
    if nid is None:
        # Fallback: bare-name lookup across all modules (ambiguous-safe — only
        # accept if exactly one match). This is the documented "name lookup
        # with a bare name → expand against current scope" rule.
        candidates = [v for k, v in name_index.items() if k.endswith("." + name) or k == name]
        if len(candidates) == 1:
            nid = candidates[0]
    if nid is None:
        leaks.append({"context": context, "name": name, "reason": "no_promoted_anchor"})
        return None
    if sym is None:
        leaks.append({
            "context": context,
            "name": name,
            "reason": "compilation_lookup_returned_none_using_name_string_anchor",
        })
    return nid


# ---------------------------------------------------------------------------
# Assignment helpers (used by S2 and S3).
# ---------------------------------------------------------------------------


def _split_around_eq(node: Any) -> tuple[Any | None, Any | None]:
    """Find the '=' or '<=' token and return (lhs_node, rhs_node).

    Skips empty intermediate SyntaxList wrappers that pyslang interposes
    between operands and the operator token.
    """
    children = list(node)
    eq_idx = None
    for i, c in enumerate(children):
        if _is_token(c) and _token_kind_name(c) in {"Equals", "LessThanEquals"}:
            eq_idx = i
            break
    if eq_idx is None:
        return None, None

    def _pick(seq):
        for c in seq:
            if _is_token(c):
                continue
            # Skip empty SyntaxList wrappers — they have no children and no tokens.
            try:
                kids = list(c)
            except TypeError:
                kids = []
            if _cls(c) == "SyntaxNode" and not kids:
                continue
            return c
        return None

    lhs = _pick(children[:eq_idx])
    # On RHS we want the last meaningful operand if multiple wrappers exist,
    # but in practice the first non-empty non-token after '=' is the expression.
    rhs = None
    for c in children[eq_idx + 1 :]:
        if _is_token(c):
            continue
        try:
            kids = list(c)
        except TypeError:
            kids = []
        if _cls(c) == "SyntaxNode" and not kids:
            continue
        rhs = c  # keep last meaningful — pyslang often wraps expr after a SyntaxList
    return lhs, rhs


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


def _lhs_target_name(lhs: Any) -> str | None:
    if lhs is None:
        return None
    toks = _identifier_tokens(lhs)
    return toks[0].valueText if toks else None


# ---------------------------------------------------------------------------
# Single-pass DFS implementing all rules in one walk.
# ---------------------------------------------------------------------------


def promote(graph: dict[str, Any], syntax_tree: Any, compilation: Any) -> None:
    """Apply S1..S5 (per-module) plus S6 (hierarchical instantiation) in a
    single DFS over the syntax tree, mutating ``graph``.

    Identity keys in ``semantic_name_index`` are hierarchical paths
    (``"<module>.<name>"`` for declarations, ``"<parent>.<inst>"`` for
    instances). Scopes are sourced from the elaborated
    ``InstanceBodySymbol`` chain so the chain matches pyslang's elaboration."""
    nodes_list = graph["nodes"]
    name_index: dict[str, str] = {}
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
        "in_param": 0,
        "in_data": 0,
        "in_port": 0,
    }

    def _cur_module():
        return state["module_stack"][-1] if state["module_stack"] else (None, "")

    def visit_pass1(node):
        idx = state["idx"]
        state["idx"] += 1
        c = _cls(node)
        gid = nodes_list[idx]["id"]
        pushed = None
        popped_module = False

        if c == "ModuleDeclarationSyntax":
            mname = _module_name_of(node)
            state["module_stack"].append((gid, mname))
            popped_module = True
            _mark(nodes_list[idx], role="module", name=mname, path=mname)
            name_index["module:" + mname] = gid
            # Also register the module's path as a top-level lookup so that
            # ``find_by_name('top')`` resolves to the module node directly.
            name_index[mname] = gid
            port_names_by_module.setdefault(mname, set())
        elif c == "ImplicitAnsiPortSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                decl = next((ch for ch in node if _cls(ch) == "DeclaratorSyntax"), None)
                ids = _identifier_tokens(decl) if decl is not None else []
                if ids:
                    pname = ids[0].valueText
                    ppath = f"{mname}.{pname}"
                    _mark(nodes_list[idx], role="port", name=pname, path=ppath)
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
                    if state["in_param"] > 0:
                        _mark(nodes_list[idx], role="param", name=dname, path=dpath)
                        _add_edge(graph, mod_gid, gid, "has_param")
                        name_index[dpath] = gid
                    elif state["in_data"] > 0 and dname not in port_names_by_module.get(mname, set()):
                        _mark(nodes_list[idx], role="net", name=dname, path=dpath)
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
        if popped_module:
            state["module_stack"].pop()

    visit_pass1(syntax_tree.root)

    # Second pass — rules S2..S6 (need name_index complete).
    state2 = {"idx": 0, "module_stack": []}

    def _cur_module2():
        return state2["module_stack"][-1] if state2["module_stack"] else (None, "")

    def visit_pass2(node):
        idx = state2["idx"]
        state2["idx"] += 1
        c = _cls(node)
        gid = nodes_list[idx]["id"]
        popped = False
        if c == "ModuleDeclarationSyntax":
            mname = _module_name_of(node)
            state2["module_stack"].append((gid, mname))
            popped = True
        mod_gid, mname = _cur_module2()
        scope = module_scope_by_name.get(mname)
        scope_path = mname
        if c == "ContinuousAssignSyntax":
            _rule_s2(graph, node, gid, nodes_list[idx], scope, name_index, leaks, scope_path)
        elif c == "ProceduralBlockSyntax":
            _rule_s3(graph, node, gid, nodes_list[idx], scope, name_index, leaks, scope_path)
        elif c == "IdentifierSelectNameSyntax":
            _rule_s4(graph, node, gid, nodes_list[idx], scope, name_index, leaks, scope_path)
        elif c == "InvocationExpressionSyntax":
            _rule_s5(graph, node, gid, nodes_list[idx], scope, name_index, leaks, scope_path)
        elif c == "HierarchyInstantiationSyntax":
            _rule_s6(graph, node, gid, nodes_list[idx], scope, name_index, leaks,
                     scope_path, mod_gid)
        if not _is_token(node):
            try:
                children = list(node)
            except TypeError:
                children = []
            for ch in children:
                visit_pass2(ch)
        if popped:
            state2["module_stack"].pop()

    visit_pass2(syntax_tree.root)
    graph["semantic_name_index"] = name_index


def _module_name_of(module_syn: Any) -> str:
    # ModuleDeclaration → ModuleHeader (first child) → identifier token
    for child in module_syn:
        if _cls(child) == "ModuleHeaderSyntax":
            ids = _identifier_tokens(child)
            if ids:
                return ids[0].valueText
    return ""


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
    if kw is None or kw.valueText != "always_ff":
        return
    _mark(gnode, role="always_ff")

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

    # Sensitivity: SignalEventExpressionSyntax.
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
                       context=f"always_ff.sensitive_to[{gid}]", scope_path=scope_path)
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
                           context=f"always_ff.drives[{gid}]", scope_path=scope_path)
            if tgt is not None and not _has_edge(graph, gid, tgt, "drives"):
                _add_edge(graph, gid, tgt, "drives")
        for rname in _identifier_names_in(rhs):
            if rname == lhs_name:
                continue
            src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                           context=f"always_ff.reads[{gid}]", scope_path=scope_path)
            if src is not None and not _has_edge(graph, gid, src, "reads"):
                _add_edge(graph, gid, src, "reads")

    # Reads from predicates and case heads.
    for d in descendants(node):
        c = _cls(d)
        if c == "ConditionalPredicateSyntax":
            for rname in _identifier_names_in(d):
                src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                               context=f"always_ff.reads.predicate[{gid}]", scope_path=scope_path)
                if src is not None and not _has_edge(graph, gid, src, "reads"):
                    _add_edge(graph, gid, src, "reads")
        elif c == "CaseStatementSyntax":
            head = next((ch for ch in d if not _is_token(ch)), None)
            if head is None:
                continue
            for rname in _identifier_names_in(head):
                src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                               context=f"always_ff.reads.case_head[{gid}]", scope_path=scope_path)
                if src is not None and not _has_edge(graph, gid, src, "reads"):
                    _add_edge(graph, gid, src, "reads")


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
    type_node_id = name_index.get("module:" + type_name)
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
