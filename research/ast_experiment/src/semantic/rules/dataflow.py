"""Dataflow rules — S2 (continuous-assign drives/reads), S3 (always_ff
sensitive_to/drives/reads), S4 (identifier reads), S5 (system-call reads),
S8 (always_comb drives/reads, mirrors S3 minus sensitivity)."""

from __future__ import annotations

import pyslang

from ..common.graph import _add_edge, _has_edge, _mark
from ..common.resolve import _resolve
from ..common.tokens import (
    _cls,
    _identifier_names_in,
    _identifier_tokens,
    _is_token,
    _lhs_target_name,
    _split_around_eq,
    _token_kind_name,
)
from ..common.walk import _descendants


def rule_s2(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S2: ContinuousAssignSyntax → drives(LHS), reads(RHS identifiers)."""
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


def rule_s3_or_s8(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S3 / S8: ProceduralBlockSyntax (always_ff / always_comb).

    Dispatch by keyword token — the pyslang ``.kind`` enum distinguishes
    AlwaysFFBlock vs AlwaysCombBlock but the keyword check on the first
    token mirrors the legacy logic exactly.
    """
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

    function_call_names: set[str] = set()
    for d in _descendants(node):
        if _cls(d) != "InvocationExpressionSyntax":
            continue
        callee = next((c for c in d if not _is_token(c)), None)
        if callee is None or _cls(callee) != "IdentifierNameSyntax":
            continue
        toks = _identifier_tokens(callee)
        if not toks:
            continue
        fn_name = toks[0].valueText
        fpath = f"{scope_path}.{fn_name}" if scope_path else fn_name
        fn_id = name_index.get(fpath)
        if fn_id is None:
            continue
        fn_node = next((nn for nn in graph["nodes"] if nn["id"] == fn_id), None)
        if fn_node is None or fn_node.get("semantic", {}).get("role") != "function":
            continue
        if not _has_edge(graph, gid, fn_id, "calls"):
            _add_edge(graph, gid, fn_id, "calls")
        function_call_names.add(fn_name)

    if do_sensitivity:
        for d in _descendants(node):
            if _cls(d) != "SignalEventExpressionSyntax":
                continue
            edge = None
            for t in _descendants(d):
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

    for d in _descendants(node):
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

    for d in _descendants(node):
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


def rule_s4(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S4: IdentifierSelectNameSyntax → reads(base)."""
    ids = _identifier_tokens(node)
    if not ids:
        return
    base = ids[0].valueText
    _mark(gnode, role="identifier_select", base=base)
    tgt = _resolve(base, scope=scope, name_index=name_index, leaks=leaks,
                   context=f"identifier_select.base[{gid}]", scope_path=scope_path)
    if tgt is not None:
        _add_edge(graph, gid, tgt, "reads")


def rule_s5(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S5: InvocationExpression with SystemName ($clog2 etc.) → reads(args)."""
    callee = next((c for c in node if not _is_token(c)), None)
    if callee is None or _cls(callee) != "SystemNameSyntax":
        return
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


# Metadata for the bucket1 checklist: rule_id annotations.
rule_s2.__rule_id__ = "S2"
rule_s3_or_s8.__rule_id__ = "S3"  # specialised at dispatch time
rule_s4.__rule_id__ = "S4"
rule_s5.__rule_id__ = "S5"


def _s4_identifier_name(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S4 covers leaf IdentifierName too — same identifier-reads logic.

    In practice the dispatch walker only invokes S4's IdentifierName entry when
    the node is NOT inside an IdentifierSelectName (which already fires S4),
    and not inside an expression where the enclosing rule reads the name.
    The legacy walker did NOT actively dispatch on IdentifierName — the
    registry entry exists purely so the bucket1 checklist marks the kind as
    promoted under S4. We keep this as a no-op metadata stub.
    """
    return


def _s8_alwayscomb(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S8 shares its implementation with S3 — dispatched via the same
    ``rule_s3_or_s8`` body. This stub exists so the registry has a distinct
    entry keyed by ``AlwaysCombBlock`` with rule_id == 'S8'."""
    rule_s3_or_s8(graph, node, gid, gnode, scope, name_index, leaks, scope_path)


def rule_s34(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S34: ProceduralBlockSyntax[AlwaysBlock] → role="always".

    Promotes the generic ``always @(...)`` procedural block — distinct from
    AlwaysFFBlock (S3) and AlwaysCombBlock (S8). The keyword token is ``always``
    (not ``always_ff`` or ``always_comb``), so the pass-1 rule_s3_or_s8 guard
    silently falls through for this kind; S34 handles it here in pass-2.

    Sensitivity list (``@(posedge clk or negedge rst)`` or ``@(a or b)``) →
    emit ``sensitive_to`` edges to identifier tokens. If an edge keyword
    (posedge/negedge/edge) precedes the identifier, it is stamped as the
    ``edge`` payload attribute (same convention as S3).

    Body assignments → ``drives`` for LHS, ``reads`` for RHS identifiers,
    using the same helpers rule_s3_or_s8 uses.
    """
    _mark(gnode, role="always")

    # Sensitivity: walk descendants for SignalEventExpressionSyntax — same
    # scan S3 uses for always_ff blocks. Level-sensitive entries
    # (``@(a or b)``) also produce SignalEventExpressionSyntax nodes but
    # without a posedge/negedge token; edge stays None in that case.
    for d in _descendants(node):
        if _cls(d) != "SignalEventExpressionSyntax":
            continue
        edge = None
        for t in _descendants(d):
            if _is_token(t) and t.valueText in {"posedge", "negedge", "edge"}:
                edge = t.valueText
                break
        ids = _identifier_tokens(d)
        if not ids:
            continue
        sig = ids[0].valueText
        tgt = _resolve(sig, scope=scope, name_index=name_index, leaks=leaks,
                       context=f"always.sensitive_to[{gid}]",
                       scope_path=scope_path)
        if tgt is not None:
            _add_edge(graph, gid, tgt, "sensitive_to", edge=edge)

    # Drives / reads: same assignment-scan as S3.
    for d in _descendants(node):
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
            tgt = _resolve(lhs_name, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"always.drives[{gid}]",
                           scope_path=scope_path)
            if tgt is not None and not _has_edge(graph, gid, tgt, "drives"):
                _add_edge(graph, gid, tgt, "drives")
        for rname in _identifier_names_in(rhs):
            if rname == lhs_name:
                continue
            src = _resolve(rname, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"always.reads[{gid}]",
                           scope_path=scope_path)
            if src is not None and not _has_edge(graph, gid, src, "reads"):
                _add_edge(graph, gid, src, "reads")


def rule_s36(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S36: ProceduralBlockSyntax[InitialBlock] → role="procedural_block",
    kind="initial".

    Promotes the ``initial begin ... end`` construct. Initial blocks have no
    explicit sensitivity list (they execute once at time zero), so we skip the
    SignalEventExpressionSyntax scan entirely and only walk body assignments for
    ``drives``/``reads`` edges — same body-scan pattern as S35 (always_latch)
    and S8 (always_comb).

    Discriminated by SyntaxKind.InitialBlock (not by the Python class name,
    per CLAUDE.md lesson 1 — ProceduralBlockSyntax is shared across
    always/always_ff/always_comb/always_latch/initial/final).
    """
    _mark(gnode, role="procedural_block", attributes={"kind": "initial"})

    # Drives / reads: walk body assignments — same scan as S35/S8.
    for d in _descendants(node):
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
            tgt = _resolve(lhs_name, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"initial.drives[{gid}]",
                           scope_path=scope_path)
            if tgt is not None and not _has_edge(graph, gid, tgt, "drives"):
                _add_edge(graph, gid, tgt, "drives")
        for rname in _identifier_names_in(rhs):
            if rname == lhs_name:
                continue
            src = _resolve(rname, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"initial.reads[{gid}]",
                           scope_path=scope_path)
            if src is not None and not _has_edge(graph, gid, src, "reads"):
                _add_edge(graph, gid, src, "reads")


def rule_s35(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S35: ProceduralBlockSyntax[AlwaysLatchBlock] → role="procedural_block",
    kind="always_latch".

    Promotes the ``always_latch begin ... end`` construct. Unlike always_ff (S3)
    and generic always (S34), there is no explicit sensitivity list — the latch
    infers sensitivity from its body. We therefore skip the
    SignalEventExpressionSyntax scan and only walk body assignments for
    ``drives``/``reads`` edges, using the same helpers as S8 (always_comb).

    Discriminated by SyntaxKind.AlwaysLatchBlock (not by the Python class name,
    per CLAUDE.md lesson 1 — ProceduralBlockSyntax is shared).
    """
    _mark(gnode, role="procedural_block", attributes={"kind": "always_latch"})

    # Drives / reads: walk body assignments — same scan as S8 (always_comb).
    for d in _descendants(node):
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
            tgt = _resolve(lhs_name, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"always_latch.drives[{gid}]",
                           scope_path=scope_path)
            if tgt is not None and not _has_edge(graph, gid, tgt, "drives"):
                _add_edge(graph, gid, tgt, "drives")
        for rname in _identifier_names_in(rhs):
            if rname == lhs_name:
                continue
            src = _resolve(rname, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"always_latch.reads[{gid}]",
                           scope_path=scope_path)
            if src is not None and not _has_edge(graph, gid, src, "reads"):
                _add_edge(graph, gid, src, "reads")

    # Conditional predicates (if/else guards reading latch_in, en, etc.)
    for d in _descendants(node):
        if _cls(d) != "ConditionalPredicateSyntax":
            continue
        for rname in _identifier_names_in(d):
            src = _resolve(rname, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"always_latch.reads.predicate[{gid}]",
                           scope_path=scope_path)
            if src is not None and not _has_edge(graph, gid, src, "reads"):
                _add_edge(graph, gid, src, "reads")


def rule_s37(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S37: ProceduralBlockSyntax[FinalBlock] → role="procedural_block",
    kind="final".

    Promotes the ``final begin ... end`` construct. Final blocks run once at
    simulation end (symmetric to ``initial`` which runs at time zero) and have
    no explicit sensitivity list, so the SignalEventExpressionSyntax scan is
    skipped entirely. Body identifiers that appear in assignment RHS positions
    emit ``reads`` edges — in practice ``final`` blocks mainly call
    ``$display`` / ``$finish`` and read local counters or signals.

    Discriminated by SyntaxKind.FinalBlock (not by the Python class name, per
    CLAUDE.md lesson 1 — ProceduralBlockSyntax is shared across
    always/always_ff/always_comb/always_latch/initial/final).
    """
    _mark(gnode, role="procedural_block", attributes={"kind": "final"})

    # Drives / reads: walk body assignments — same scan as S36/S35/S8.
    for d in _descendants(node):
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
            tgt = _resolve(lhs_name, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"final.drives[{gid}]",
                           scope_path=scope_path)
            if tgt is not None and not _has_edge(graph, gid, tgt, "drives"):
                _add_edge(graph, gid, tgt, "drives")
        for rname in _identifier_names_in(rhs):
            if rname == lhs_name:
                continue
            src = _resolve(rname, scope=scope, name_index=name_index,
                           leaks=leaks,
                           context=f"final.reads[{gid}]",
                           scope_path=scope_path)
            if src is not None and not _has_edge(graph, gid, src, "reads"):
                _add_edge(graph, gid, src, "reads")


def rule_s46(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S46: NetAliasSyntax → ``aliases`` edges between consecutive identifier pairs.

    ``alias a = b = c;`` (SV §10.11) declares bidirectional net equivalence.
    The rule emits ``aliases`` edges pairwise between *consecutive* identifiers
    in the alias chain only (a↔b, b↔c) rather than the full Cartesian product
    (a↔b, b↔c, a↔c).  Consecutive pairs capture the syntactic grouping the
    designer wrote; consumers that need full transitivity can close over the
    edge relation themselves.

    Each pair produces two directed edges (src→dst *and* dst→src) to model
    the bidirectionality of net aliasing.

    Edge metadata:
      type  = "aliases"
      (no additional payload attributes — the relationship is symmetric)

    No new node is created; the NetAliasSyntax node stays as BLOB in the
    Bucket-1 sense.  Resolution: ``<scope_path>.<name>`` via name_index;
    fallback to ``_unresolved.<name>`` with ``unresolved=True`` when absent.
    """
    # The SeparatedList child (child index 2) holds:
    #   IdentifierNameSyntax  Equals  IdentifierNameSyntax  Equals  ...
    # Collect the identifier tokens in order.
    sep_list = next(
        (c for c in node
         if not _is_token(c) and str(getattr(c, "kind", "")).endswith("SeparatedList")),
        None,
    )
    if sep_list is None:
        return

    names: list[str] = []
    try:
        for ch in sep_list:
            if _is_token(ch):
                continue
            # Each non-token child is an IdentifierNameSyntax
            ids = _identifier_tokens(ch)
            if ids:
                names.append(ids[0].valueText)
    except TypeError:
        return

    if len(names) < 2:
        return

    def _res(name: str) -> str:
        path = f"{scope_path}.{name}" if scope_path else name
        gid_resolved = name_index.get(path)
        if gid_resolved is not None:
            return gid_resolved
        # Fallback: unresolved placeholder
        return f"_unresolved.{name}"

    # Emit bidirectional aliases edges for each consecutive pair.
    for i in range(len(names) - 1):
        a_name, b_name = names[i], names[i + 1]
        a_gid = _res(a_name)
        b_gid = _res(b_name)
        a_unresolved = isinstance(a_gid, str) and a_gid.startswith("_unresolved.")
        b_unresolved = isinstance(b_gid, str) and b_gid.startswith("_unresolved.")
        kw_a = {"unresolved": True} if a_unresolved else {}
        kw_b = {"unresolved": True} if b_unresolved else {}
        _add_edge(graph, a_gid, b_gid, "aliases", **kw_a, **kw_b)
        _add_edge(graph, b_gid, a_gid, "aliases", **kw_a, **kw_b)


def _s46_stub(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S46 ownership marker — NetAlias edge-only promotion.

    This stub exists so the bucket-1 checklist can mark SyntaxKind.NetAlias as
    PROMOTE under S46.  The actual work is done inline in pass-1 dispatch
    (see dispatch.py) because the enclosing module gid must already be bound
    before alias edges can be emitted.  At rule-dispatch time (pass 2) this
    stub is a no-op.
    """
    return


def _s54_stub(graph, node, gid, gnode, scope, name_index, leaks, scope_path="", **_):
    """S54 ownership marker — NetDeclaration group-node promotion.

    ``wire``/``tri``/``supply0``/``wire signed [7:0]`` net declarations
    (SV §6.7) become group nodes with role="net_decl" carrying
    ``{net_type, signed}`` attributes.  Each child Declarator is promoted as
    role="net" (same convention S1 applies to DataDeclarationSyntax-wrapped
    nets) and connected back to the group via ``groups_net`` edges; the
    enclosing module additionally emits ``has_net_decl`` to the group and
    ``has_net`` to each child net.

    All work happens in pass-1 dispatch (see dispatch.py) because the
    enclosing module gid must already be bound and the per-net Declarator
    children need access to ``net_decl_stack`` during the same recursive
    walk.  At pass-2 rule-dispatch time this stub is a no-op; it exists so
    the bucket-1 checklist marks SyntaxKind.NetDeclaration as PROMOTE under
    S54.
    """
    return


_s4_identifier_name.__rule_id__ = "S4"
_s8_alwayscomb.__rule_id__ = "S8"
rule_s34.__rule_id__ = "S34"
rule_s35.__rule_id__ = "S35"
rule_s36.__rule_id__ = "S36"
rule_s37.__rule_id__ = "S37"
rule_s46.__rule_id__ = "S46"
_s46_stub.__rule_id__ = "S46"
_s54_stub.__rule_id__ = "S54"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ContinuousAssign, rule_s2),
    (pyslang.SyntaxKind.AlwaysFFBlock, rule_s3_or_s8),
    (pyslang.SyntaxKind.AlwaysCombBlock, _s8_alwayscomb),
    (pyslang.SyntaxKind.AlwaysBlock, rule_s34),
    (pyslang.SyntaxKind.AlwaysLatchBlock, rule_s35),
    (pyslang.SyntaxKind.InitialBlock, rule_s36),
    (pyslang.SyntaxKind.FinalBlock, rule_s37),
    (pyslang.SyntaxKind.IdentifierSelectName, rule_s4),
    (pyslang.SyntaxKind.IdentifierName, _s4_identifier_name),
    (pyslang.SyntaxKind.SystemName, rule_s5),
    (pyslang.SyntaxKind.InvocationExpression, rule_s5),
    (pyslang.SyntaxKind.NetAlias, _s46_stub),
    (pyslang.SyntaxKind.NetDeclaration, _s54_stub),
]
