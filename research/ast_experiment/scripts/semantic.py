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
    top = list(compilation.getRoot().topInstances)
    if not top:
        return None
    return top[0].body


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
) -> str | None:
    """Resolve ``name`` to a graph id; record a leak if we fall back."""
    sym = _lookup_name(scope, name)
    nid = name_index.get(name)
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
    """Apply S1..S5 in a single DFS over the syntax tree, mutating ``graph``."""
    nodes_list = graph["nodes"]
    scope = _module_scope(compilation)
    name_index: dict[str, str] = {}
    leaks: list[dict[str, str]] = graph.setdefault("semantic_leaks", [])

    # Pass 1 — index nodes and snapshot per-class subtrees we'll need.
    # We collect, in DFS order, the dfs_index plus the syntax wrapper *only*
    # for the duration of the immediate frame.  All decisions are taken
    # before we leave the frame.
    port_names: set[str] = set()

    # First pass: promote module + ports/params/nets, build name_index.
    # Use a recursive walker with enter/exit so we can track which container
    # a DeclaratorSyntax sits inside (parameter? data decl? port header?).
    state = {
        "idx": 0,
        "module_gid": None,
        "in_param": 0,
        "in_data": 0,
        "in_port": 0,
    }

    def visit_pass1(node):
        idx = state["idx"]
        state["idx"] += 1
        c = _cls(node)
        gid = nodes_list[idx]["id"]
        pushed = None

        if c == "ModuleDeclarationSyntax" and state["module_gid"] is None:
            state["module_gid"] = gid
            mname = _module_name_of(node)
            _mark(nodes_list[idx], role="module", name=mname)
            name_index["module:" + mname] = gid
        elif c == "ImplicitAnsiPortSyntax" and state["module_gid"] is not None:
            decl = next((ch for ch in node if _cls(ch) == "DeclaratorSyntax"), None)
            ids = _identifier_tokens(decl) if decl is not None else []
            if ids:
                pname = ids[0].valueText
                _mark(nodes_list[idx], role="port", name=pname)
                _add_edge(graph, state["module_gid"], gid, "has_port")
                name_index[pname] = gid
                port_names.add(pname)
            pushed = "in_port"
        elif c == "ParameterDeclarationSyntax":
            pushed = "in_param"
        elif c == "DataDeclarationSyntax":
            pushed = "in_data"
        elif c == "DeclaratorSyntax" and state["module_gid"] is not None:
            ids = _identifier_tokens(node)
            if ids and state["in_port"] == 0:
                dname = ids[0].valueText
                if state["in_param"] > 0:
                    _mark(nodes_list[idx], role="param", name=dname)
                    _add_edge(graph, state["module_gid"], gid, "has_param")
                    name_index[dname] = gid
                elif state["in_data"] > 0 and dname not in port_names:
                    _mark(nodes_list[idx], role="net", name=dname)
                    _add_edge(graph, state["module_gid"], gid, "has_net")
                    name_index[dname] = gid

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

    visit_pass1(syntax_tree.root)
    _ = state["module_gid"]  # module_gid retained inside state

    # Second pass — rules S2..S5 (need name_index complete).
    state2 = {"idx": 0}

    def visit_pass2(node):
        idx = state2["idx"]
        state2["idx"] += 1
        c = _cls(node)
        gid = nodes_list[idx]["id"]
        if c == "ContinuousAssignSyntax":
            _rule_s2(graph, node, gid, nodes_list[idx], scope, name_index, leaks)
        elif c == "ProceduralBlockSyntax":
            _rule_s3(graph, node, gid, nodes_list[idx], scope, name_index, leaks)
        elif c == "IdentifierSelectNameSyntax":
            _rule_s4(graph, node, gid, nodes_list[idx], scope, name_index, leaks)
        elif c == "InvocationExpressionSyntax":
            _rule_s5(graph, node, gid, nodes_list[idx], scope, name_index, leaks)
        if _is_token(node):
            return
        try:
            children = list(node)
        except TypeError:
            return
        for ch in children:
            visit_pass2(ch)

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


def _rule_s2(graph, node, gid, gnode, scope, name_index, leaks):
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
                       context=f"continuous_assign.lhs[{gid}]")
        if tgt is not None:
            _add_edge(graph, gid, tgt, "drives")
    seen_reads: set[str] = set()
    for rname in _identifier_names_in(rhs):
        if rname == lhs_name or rname in seen_reads:
            continue
        seen_reads.add(rname)
        src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                       context=f"continuous_assign.rhs[{gid}]")
        if src is not None:
            _add_edge(graph, gid, src, "reads")


def _rule_s3(graph, node, gid, gnode, scope, name_index, leaks):
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
                       context=f"always_ff.sensitive_to[{gid}]")
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
                           context=f"always_ff.drives[{gid}]")
            if tgt is not None and not _has_edge(graph, gid, tgt, "drives"):
                _add_edge(graph, gid, tgt, "drives")
        for rname in _identifier_names_in(rhs):
            if rname == lhs_name:
                continue
            src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                           context=f"always_ff.reads[{gid}]")
            if src is not None and not _has_edge(graph, gid, src, "reads"):
                _add_edge(graph, gid, src, "reads")

    # Reads from predicates and case heads.
    for d in descendants(node):
        c = _cls(d)
        if c == "ConditionalPredicateSyntax":
            for rname in _identifier_names_in(d):
                src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                               context=f"always_ff.reads.predicate[{gid}]")
                if src is not None and not _has_edge(graph, gid, src, "reads"):
                    _add_edge(graph, gid, src, "reads")
        elif c == "CaseStatementSyntax":
            head = next((ch for ch in d if not _is_token(ch)), None)
            if head is None:
                continue
            for rname in _identifier_names_in(head):
                src = _resolve(rname, scope=scope, name_index=name_index, leaks=leaks,
                               context=f"always_ff.reads.case_head[{gid}]")
                if src is not None and not _has_edge(graph, gid, src, "reads"):
                    _add_edge(graph, gid, src, "reads")


def _rule_s4(graph, node, gid, gnode, scope, name_index, leaks):
    ids = _identifier_tokens(node)
    if not ids:
        return
    base = ids[0].valueText
    _mark(gnode, role="identifier_select", base=base)
    tgt = _resolve(base, scope=scope, name_index=name_index, leaks=leaks,
                   context=f"identifier_select.base[{gid}]")
    if tgt is not None:
        _add_edge(graph, gid, tgt, "reads")


def _rule_s5(graph, node, gid, gnode, scope, name_index, leaks):
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
                       context=f"system_call.arg[{gid}]")
        if tgt is not None:
            _add_edge(graph, gid, tgt, "reads")


# ---------------------------------------------------------------------------
# Public queries.
# ---------------------------------------------------------------------------


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
    nid = graph.get("semantic_name_index", {}).get(name)
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
    follow what they read; repeat. Returns the set of visited node ids."""
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
        frontier = nxt
    return seen
