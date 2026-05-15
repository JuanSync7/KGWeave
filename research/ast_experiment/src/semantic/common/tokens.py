"""Token / syntax-node primitives — pure helpers, no graph or compilation
dependencies. Sourced verbatim from the legacy scripts/semantic.py."""

from __future__ import annotations

from typing import Any


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
            try:
                kids = list(c)
            except TypeError:
                kids = []
            if _cls(c) == "SyntaxNode" and not kids:
                continue
            return c
        return None

    lhs = _pick(children[:eq_idx])
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
        rhs = c
    return lhs, rhs


def _lhs_target_name(lhs: Any) -> str | None:
    if lhs is None:
        return None
    toks = _identifier_tokens(lhs)
    return toks[0].valueText if toks else None


def _expression_text(node: Any) -> str:
    """Concatenate every Token.rawText under ``node`` in DFS order.

    Used to project the textual value of a parameter-override expression
    without relying on source-string slicing or regex. Leading trivia is
    suppressed on the very first token so the result is left-trimmed.
    """
    parts: list[str] = []
    first = [True]

    def go(n: Any) -> None:
        if _is_token(n):
            if not first[0]:
                for tr in n.trivia:
                    parts.append(tr.getRawText())
            first[0] = False
            parts.append(n.rawText)
            return
        try:
            kids = list(n)
        except TypeError:
            kids = []
        for c in kids:
            go(c)

    go(node)
    return "".join(parts).strip()


def _module_name_of(module_syn: Any) -> str:
    """ModuleDeclaration → ModuleHeader (first child) → identifier token."""
    for child in module_syn:
        if _cls(child) == "ModuleHeaderSyntax":
            ids = _identifier_tokens(child)
            if ids:
                return ids[0].valueText
    return ""


def _function_name_of(fn_syn: Any) -> str:
    """Return the function name token from a FunctionDeclarationSyntax.

    Walks the FunctionPrototypeSyntax child and returns the LAST Identifier
    token encountered before the FunctionPortListSyntax subtree.
    """
    proto = next((c for c in fn_syn if _cls(c) == "FunctionPrototypeSyntax"), None)
    if proto is None:
        return ""
    # Inline descendants walk — common.walk._descendants is the same logic
    # but we avoid a circular import by inlining the trivial 4-line variant.
    def _descendants_local(n: Any):
        yield n
        if _is_token(n):
            return
        try:
            kids = list(n)
        except TypeError:
            return
        for c in kids:
            yield from _descendants_local(c)

    last_id = ""
    for d in _descendants_local(proto):
        if _cls(d) == "FunctionPortListSyntax":
            break
        if _is_token(d) and _token_kind_name(d) == "Identifier":
            last_id = d.valueText
    return last_id


def _property_name_of(prop_syn: Any) -> str:
    """Return the property name from a PropertyDeclarationSyntax.

    Grammar: ``[attrs] property <Identifier> [ports] ; <spec> endproperty``.
    The property name is the first direct Identifier Token child following
    the ``property`` keyword. Walking direct children only avoids descending
    into the property body (where IdentifierName tokens belong to the
    expression, not the declaration).
    """
    saw_property_kw = False
    for ch in prop_syn:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind == "PropertyKeyword":
                saw_property_kw = True
                continue
            if saw_property_kw and kind == "Identifier":
                return ch.valueText
    return ""


def _sequence_name_of(seq_syn: Any) -> str:
    """Return the sequence name from a SequenceDeclarationSyntax.

    Grammar: ``[attrs] sequence <Identifier> [ports] ; <expr> endsequence``.
    The sequence name is the first direct Identifier Token child following
    the ``sequence`` keyword. Walking direct children only avoids descending
    into the sequence body (where IdentifierName tokens belong to the
    expression, not the declaration).
    """
    saw_sequence_kw = False
    for ch in seq_syn:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind == "SequenceKeyword":
                saw_sequence_kw = True
                continue
            if saw_sequence_kw and kind == "Identifier":
                return ch.valueText
    return ""


def _assertion_label_of(assertion_syn: Any) -> str:
    """Return the optional ``label:`` identifier of a concurrent-assertion
    statement, or ``""`` if absent.

    Grammar: ``[NamedLabelSyntax] <assert|assume|cover|restrict|expect>
    <property|sequence> ( <spec> ) [action]``. Pyslang parses the ``label:``
    prefix as a ``NamedLabelSyntax`` direct child of the
    ``ConcurrentAssertionStatementSyntax``. Walk direct children only to avoid
    descending into the spec body.
    """
    for ch in assertion_syn:
        if _is_token(ch):
            continue
        if _cls(ch) == "NamedLabelSyntax":
            ids = _identifier_tokens(ch)
            if ids:
                return ids[0].valueText
    return ""


def _clocking_name_of(clk_syn: Any) -> str:
    """Return the clocking-block name from a ClockingDeclarationSyntax.

    Grammar: ``[default|global] clocking <Identifier> @(event); ... endclocking``.
    The name is the first direct Identifier Token child following the
    ``clocking`` keyword. Walking direct children only avoids descending into
    the clocking-item subtree (where Identifier tokens belong to signal
    references, not the declaration).
    """
    saw_clocking_kw = False
    for ch in clk_syn:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind == "ClockingKeyword":
                saw_clocking_kw = True
                continue
            if saw_clocking_kw and kind == "Identifier":
                return ch.valueText
    return ""


def _clocking_modifier_of(clk_syn: Any) -> str:
    """Return ``"default"``, ``"global"``, or ``""`` based on the leading
    keyword token of a ClockingDeclarationSyntax.

    The ``default``/``global`` modifier (if present) appears as a direct
    Token child before the ``ClockingKeyword``. Detect structurally — no
    regex on source text.
    """
    for ch in clk_syn:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind == "DefaultKeyword":
                return "default"
            if kind == "GlobalKeyword":
                return "global"
            if kind == "ClockingKeyword":
                return ""
    return ""


def _covergroup_name_of(cg_syn: Any) -> str:
    """Return the covergroup name from a CovergroupDeclarationSyntax.

    Grammar: ``covergroup <Identifier> [ports] [@(event)]; <items> endgroup``.
    The covergroup name is the first direct Identifier Token child following
    the ``CoverGroupKeyword`` token. Walking direct children only avoids
    descending into the covergroup body (where Identifier tokens belong to
    coverpoint labels and signal references, not the declaration itself).
    """
    saw_covergroup_kw = False
    for ch in cg_syn:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind == "CoverGroupKeyword":
                saw_covergroup_kw = True
                continue
            if saw_covergroup_kw and kind == "Identifier":
                return ch.valueText
    return ""


def _covergroup_has_clocking_event(cg_syn: Any) -> bool:
    """True if the CovergroupDeclarationSyntax has a clocking event clause
    (``@(posedge clk)`` etc.) as a direct child.

    Pyslang surfaces the event-control clause as an ``EventControlSyntax``
    family node — ``EventControlWithExpressionSyntax``, ``EventControlSyntax``,
    or ``ImplicitEventControlSyntax`` — as a direct child of the covergroup
    declaration. Walking direct children only avoids being confused by event
    controls inside the covergroup body (e.g. inside @@(block_event) clauses).
    """
    for ch in cg_syn:
        if _is_token(ch):
            continue
        cn = _cls(ch)
        if cn.startswith("EventControl") or cn == "ImplicitEventControlSyntax":
            return True
    return False


def _named_label_of(node: Any) -> str:
    """Return the optional ``label:`` identifier of any syntax node, or
    ``""`` if absent.

    Several coverage / assertion sub-statements carry an optional
    ``NamedLabelSyntax`` direct child (``cp_full: coverpoint full;``,
    ``cx_push_full: cross cp_push, cp_full;``, etc.). Walking direct
    children only avoids descending into the body where Identifier tokens
    belong to expression references, not the declaration label.
    """
    for ch in node:
        if _is_token(ch):
            continue
        if _cls(ch) == "NamedLabelSyntax":
            ids = _identifier_tokens(ch)
            if ids:
                return ids[0].valueText
    return ""


def _coverpoint_expression(node: Any) -> tuple[str, bool]:
    """Extract the cover-expression of a CoverpointSyntax.

    Grammar fragment: ``[label:] coverpoint <expr> [iff(...)] [{ bins }] ;``.
    The expression is the first non-token, non-SyntaxList, non-NamedLabel,
    non-ImplicitType direct child following the ``CoverPointKeyword`` token.

    Returns ``(expr_text, expr_blob)`` where ``expr_blob`` is True when the
    expression is anything other than a single bare identifier name. For the
    simple identifier case we return its valueText and ``expr_blob=False``.
    """
    seen_kw = False
    for ch in node:
        if _is_token(ch):
            if _token_kind_name(ch) == "CoverPointKeyword":
                seen_kw = True
            continue
        if not seen_kw:
            continue
        cn = _cls(ch)
        if cn in {"NamedLabelSyntax", "ImplicitTypeSyntax"}:
            continue
        # SyntaxList wrappers (attribute lists, bin lists) are skipped.
        if cn == "SyntaxNode":
            continue
        # Found the expression node. Simple identifier?
        if cn == "IdentifierNameSyntax":
            toks = _identifier_tokens(ch)
            if len(toks) == 1:
                return toks[0].valueText, False
        return "", True
    return "", True


def _cover_cross_members(node: Any) -> list[str]:
    """Extract the coverpoint-name list referenced by a CoverCrossSyntax.

    Grammar fragment: ``[label:] cross <cp_a>, <cp_b> [, ...] [iff(...)]
    [{ bins }] ;``. The member list is a SeparatedList of IdentifierName
    nodes that directly follows the ``CrossKeyword`` token. Walking direct
    children only avoids descending into the cross body (``CoverageBins``
    subtrees where Identifier tokens are bin-selector references).
    """
    seen_kw = False
    members: list[str] = []
    for ch in node:
        if _is_token(ch):
            if _token_kind_name(ch) == "CrossKeyword":
                seen_kw = True
            continue
        if not seen_kw:
            continue
        cn = _cls(ch)
        if cn == "NamedLabelSyntax":
            continue
        # Walk children of the SeparatedList for IdentifierName entries.
        try:
            kids = list(ch)
        except TypeError:
            kids = []
        for k in kids:
            if _is_token(k):
                continue
            if _cls(k) == "IdentifierNameSyntax":
                toks = _identifier_tokens(k)
                if toks:
                    members.append(toks[0].valueText)
        if members:
            return members
        # If the direct child IS an IdentifierName itself (single-member case)
        if cn == "IdentifierNameSyntax":
            toks = _identifier_tokens(ch)
            if toks:
                members.append(toks[0].valueText)
        return members
    return members


def _class_name_of(cls_syn: Any) -> str:
    """Return the class name from a ClassDeclarationSyntax.

    Grammar: ``[virtual|interface] class <Identifier> [#(params)]
    [extends ...] [implements ...] ; <items> endclass``. The name is the
    first direct Identifier Token child following the ``ClassKeyword``
    token. Walking direct children only avoids descending into the class
    body (where Identifier tokens belong to members and references).
    """
    saw_class_kw = False
    for ch in cls_syn:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind == "ClassKeyword":
                saw_class_kw = True
                continue
            if saw_class_kw and kind == "Identifier":
                return ch.valueText
    return ""


def _class_modifiers_of(cls_syn: Any) -> dict[str, bool]:
    """Return structural modifiers of a ClassDeclarationSyntax.

    Grammar: ``[virtual] [interface] [final] class <Identifier>
    [#(params)] ...``. Modifier keywords appear as direct Token children
    before the ``ClassKeyword``. The parameter-port list (``#(...)``)
    appears as a ``ParameterPortListSyntax`` direct child after the
    identifier. Detect structurally — no regex on source text.
    """
    out = {
        "virtual": False,
        "interface_class": False,
        "final": False,
        "parameterized": False,
    }
    saw_class_kw = False
    for ch in cls_syn:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind == "ClassKeyword":
                saw_class_kw = True
                continue
            if not saw_class_kw:
                if kind == "VirtualKeyword":
                    out["virtual"] = True
                elif kind == "InterfaceKeyword":
                    out["interface_class"] = True
                elif kind == "FinalKeyword":
                    out["final"] = True
            continue
        if saw_class_kw and _cls(ch) == "ParameterPortListSyntax":
            out["parameterized"] = True
    return out


def _class_ref_name_of(name_syn: Any) -> str:
    """Return the bare class/interface name from an extends/implements
    reference. The reference is either an ``IdentifierNameSyntax`` (simple
    ``base``), a ``ClassNameSyntax`` (``base #(.T(...))``), or a
    ``ScopedNameSyntax`` (``pkg::base``). In every case the meaningful
    name is the LAST direct ``Identifier`` token discovered in a
    depth-first walk that descends into nested ScopedName / ClassName
    nodes but not into ParameterValueAssignment payloads.

    Returns the empty string if no identifier is found.
    """
    if name_syn is None:
        return ""
    if _is_token(name_syn):
        return name_syn.valueText if _token_kind_name(name_syn) == "Identifier" else ""
    cls_name = _cls(name_syn)
    # For ClassNameSyntax: first direct Identifier token IS the class name;
    # any later identifiers belong to the parameter-value-assignment payload.
    if cls_name == "ClassNameSyntax":
        for ch in name_syn:
            if _is_token(ch) and _token_kind_name(ch) == "Identifier":
                return ch.valueText
        return ""
    # For ScopedNameSyntax: take the right-most identifier (terminal segment).
    if cls_name == "ScopedNameSyntax":
        last = ""
        for ch in name_syn:
            sub = _class_ref_name_of(ch)
            if sub:
                last = sub
        return last
    # IdentifierNameSyntax or generic wrapper — first identifier wins.
    for ch in name_syn:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier":
            return ch.valueText
    # Fallback: descend.
    for ch in name_syn:
        if _is_token(ch):
            continue
        sub = _class_ref_name_of(ch)
        if sub:
            return sub
    return ""


def _extends_clause_target(ec_syn: Any) -> tuple[str, bool]:
    """Return ``(parent_class_name, has_param_overrides)`` for an
    ExtendsClauseSyntax. The clause grammar is
    ``extends <Name> [#(...)]`` where ``<Name>`` is the first non-token
    direct child of the clause. ``has_param_overrides`` is True iff the
    inner Name is a ``ClassNameSyntax`` whose direct children contain a
    ``ParameterValueAssignmentSyntax``.
    """
    for ch in ec_syn:
        if _is_token(ch):
            continue
        nm = _class_ref_name_of(ch)
        params = False
        if _cls(ch) == "ClassNameSyntax":
            for sub in ch:
                if not _is_token(sub) and _cls(sub) == "ParameterValueAssignmentSyntax":
                    params = True
                    break
        return nm, params
    return "", False


def _package_import_items_of(decl_syn: Any) -> list[tuple[str, str]]:
    """Return the ordered list of ``(pkg_name, item)`` tuples from a
    PackageImportDeclarationSyntax or PackageExportDeclarationSyntax.

    Grammar: ``(import|export) <pkg>::(<id>|*) [, <pkg>::(<id>|*)]* ;``.
    Each ``<pkg>::<rhs>`` clause surfaces as a ``PackageImportItemSyntax``
    direct child of a SeparatedList wrapper. ``item`` is the identifier
    valueText or the literal string ``"*"`` for the wildcard form.

    Returns ``[]`` if no items are found — caller decides whether to record
    a leak. Walks direct children only; commas inside the SeparatedList are
    Token nodes and are skipped by the _is_token guard.
    """
    out: list[tuple[str, str]] = []

    def _consume_item(item_syn: Any) -> None:
        pkg_name = ""
        item_label = ""
        saw_colon_colon = False
        for sub in item_syn:
            if _is_token(sub):
                tk = _token_kind_name(sub)
                if tk == "Identifier":
                    if not saw_colon_colon:
                        pkg_name = sub.valueText
                    else:
                        item_label = sub.valueText
                elif tk == "DoubleColon":
                    saw_colon_colon = True
                elif tk == "Star" and saw_colon_colon:
                    item_label = "*"
        if pkg_name and item_label:
            out.append((pkg_name, item_label))

    for ch in decl_syn:
        if _is_token(ch):
            continue
        if _cls(ch) == "PackageImportItemSyntax":
            _consume_item(ch)
            continue
        # SeparatedList wrapper surfaced as a generic SyntaxNode — descend
        # one level, skip comma tokens, consume each item.
        for sub in ch:
            if _is_token(sub):
                continue
            if _cls(sub) == "PackageImportItemSyntax":
                _consume_item(sub)
    return out


def _package_import_item_parts(item_syn: Any) -> tuple[str, str] | None:
    """Extract ``(pkg_name, symbol)`` from a single ``PackageImportItemSyntax``.

    ``symbol`` is the identifier valueText or ``"*"`` for the wildcard form.
    Returns ``None`` if the node is malformed (missing package name or symbol).
    Used by S50's pass-2 rule which receives the item node directly.
    """
    pkg_name = ""
    symbol = ""
    saw_colon_colon = False
    try:
        for sub in item_syn:
            if not _is_token(sub):
                continue
            tk = _token_kind_name(sub)
            if tk == "Identifier":
                if not saw_colon_colon:
                    pkg_name = sub.valueText
                else:
                    symbol = sub.valueText
            elif tk == "DoubleColon":
                saw_colon_colon = True
            elif tk == "Star" and saw_colon_colon:
                symbol = "*"
    except TypeError:
        return None
    return (pkg_name, symbol) if (pkg_name and symbol) else None


def _implements_clause_targets(ic_syn: Any) -> list[str]:
    """Return the ordered list of implemented interface-class names from an
    ImplementsClauseSyntax. The clause grammar is
    ``implements <Name>[, <Name>]*``; pyslang wraps the comma-separated
    name list inside a ``SeparatedSyntaxList`` (surfaced as a generic
    SyntaxNode) under the clause. Walks one level into that wrapper and
    collects each direct IdentifierName / ClassName / ScopedName child.
    """
    out: list[str] = []
    name_node_classes = {"IdentifierNameSyntax", "ClassNameSyntax", "ScopedNameSyntax"}
    for ch in ic_syn:
        if _is_token(ch):
            continue
        # Direct name child (no separated-list wrapper interposed).
        if _cls(ch) in name_node_classes:
            nm = _class_ref_name_of(ch)
            if nm:
                out.append(nm)
            continue
        # Wrapper (SeparatedSyntaxList surfaced as a generic SyntaxNode) —
        # descend one level, skip comma tokens, collect each name ref.
        for sub in ch:
            if _is_token(sub):
                continue
            if _cls(sub) in name_node_classes:
                sub_nm = _class_ref_name_of(sub)
                if sub_nm:
                    out.append(sub_nm)
    return out


_CLASS_PROPERTY_QUALIFIER_KEYWORDS: dict[str, str] = {
    "StaticKeyword": "static",
    "ConstKeyword": "const",
    "RandKeyword": "rand",
    "RandCKeyword": "randc",
    "ProtectedKeyword": "protected",
    "LocalKeyword": "local",
}


_CONSTRAINT_QUALIFIER_KEYWORDS: dict[str, str] = {
    "StaticKeyword": "static",
    "PureKeyword": "pure",
    "ExternKeyword": "extern",
}


def _constraint_name_of(c_syn: Any) -> str:
    """Return the constraint name from a ConstraintDeclarationSyntax or
    ConstraintPrototypeSyntax.

    Grammar: ``[static|pure|extern] constraint <Identifier> ( { body } | ; )``.
    The constraint name is the first Identifier token in the first
    ``IdentifierNameSyntax`` direct child after the ``ConstraintKeyword``
    token. Walking direct children avoids descending into the constraint
    body where identifiers refer to property references, not the
    declaration itself.
    """
    saw_constraint_kw = False
    for ch in c_syn:
        if _is_token(ch):
            if _token_kind_name(ch) == "ConstraintKeyword":
                saw_constraint_kw = True
            continue
        if not saw_constraint_kw:
            continue
        if _cls(ch) == "IdentifierNameSyntax":
            toks = _identifier_tokens(ch)
            if toks:
                return toks[0].valueText
    return ""


_CLASS_METHOD_QUALIFIER_KEYWORDS: dict[str, str] = {
    "VirtualKeyword": "virtual",
    "PureKeyword": "pure",
    "ExternKeyword": "extern",
    "StaticKeyword": "static",
    "ProtectedKeyword": "protected",
    "LocalKeyword": "local",
}


def _qualifier_tokens_of(node: Any, mapping: dict[str, str]) -> dict[str, bool]:
    """Walk direct children of ``node`` looking for a TokenList SyntaxNode
    that holds class-member qualifier tokens (``static``/``virtual``/``rand``
    etc.). Returns a dict mapping every key in ``mapping.values()`` to a bool
    indicating presence. Direct-child Token siblings are also inspected for
    robustness (some pyslang grammar variants surface qualifiers loose rather
    than wrapped in a TokenList).
    """
    out = {label: False for label in mapping.values()}
    for ch in node:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind in mapping:
                out[mapping[kind]] = True
            continue
        # Walk one level into TokenList wrappers (surfaced as generic SyntaxNode).
        try:
            kids = list(ch)
        except TypeError:
            continue
        for sub in kids:
            if _is_token(sub):
                kind = _token_kind_name(sub)
                if kind in mapping:
                    out[mapping[kind]] = True
    return out


def _class_method_name_and_kind(method_node: Any) -> tuple[str, str, str | None]:
    """Return (name, kind, return_type) for a ClassMethodDeclarationSyntax or
    ClassMethodPrototypeSyntax.

    kind is one of ``"function"`` / ``"task"`` / ``"new"`` / ``"prototype"``
    (the last is the role hint for an inner ``FunctionPrototypeSyntax``-only
    body — i.e. a method prototype declaration).
    return_type is the textual return type for functions (``"void"``,
    ``"int"``, a NamedType identifier, ...) or ``None`` for tasks /
    constructors / implicit-return forms.
    """
    inner = None
    for ch in method_node:
        if _is_token(ch):
            continue
        cn = _cls(ch)
        if cn in {"FunctionDeclarationSyntax", "TaskDeclarationSyntax",
                  "FunctionPrototypeSyntax"}:
            inner = ch
            break
    if inner is None:
        return "", "function", None

    inner_cls = _cls(inner)
    if inner_cls == "TaskDeclarationSyntax":
        # Task: name is in the inner FunctionPrototypeSyntax (yes, pyslang
        # reuses the prototype class for tasks too).
        proto = next((c for c in inner if _cls(c) == "FunctionPrototypeSyntax"), None)
        if proto is None:
            return "", "task", None
        name, _rt = _function_proto_name_and_return(proto)
        return name, "task", None

    if inner_cls == "FunctionDeclarationSyntax":
        proto = next((c for c in inner if _cls(c) == "FunctionPrototypeSyntax"), None)
        if proto is None:
            return "", "function", None
        name, rt = _function_proto_name_and_return(proto)
        if _is_constructor(proto):
            return "new", "new", None
        return name, "function", rt

    # FunctionPrototypeSyntax direct (no enclosing decl) — prototype-only form.
    name, rt = _function_proto_name_and_return(inner)
    if _is_constructor(inner):
        return "new", "new", None
    # The caller (ClassMethodPrototype branch) overrides kind to "prototype"
    # if this is a pure-virtual / extern declaration.
    return name, "function", rt


def _is_constructor(proto: Any) -> bool:
    """True if a FunctionPrototypeSyntax's name child is a KeywordNameSyntax
    holding a ``new`` keyword (ConstructorName)."""
    for ch in proto:
        if _is_token(ch):
            continue
        if _cls(ch) == "KeywordNameSyntax":
            for sub in ch:
                if _is_token(sub) and _token_kind_name(sub) == "NewKeyword":
                    return True
    return False


def _function_proto_name_and_return(proto: Any) -> tuple[str, str | None]:
    """Extract (name, return_type_text) from a FunctionPrototypeSyntax.

    Grammar: ``function [lifetime] <return_type_or_void> <name> ( ports )``.
    The return type is the first non-token, non-SyntaxList child after the
    ``FunctionKeyword`` token; the name is the next non-token child after
    that (an IdentifierName / KeywordName / ScopedName). For implicit return
    (``ImplicitTypeSyntax``) we return ``None`` for the return type.
    """
    return_node = None
    name_node = None
    saw_fn_kw = False
    for ch in proto:
        if _is_token(ch):
            if _token_kind_name(ch) == "FunctionKeyword":
                saw_fn_kw = True
            continue
        if not saw_fn_kw:
            continue
        cn = _cls(ch)
        # Skip SyntaxList wrappers (lifetime / attributes).
        if cn == "SyntaxNode":
            try:
                kids = list(ch)
            except TypeError:
                kids = []
            # An empty SyntaxList is the lifetime placeholder; skip.
            if not kids:
                continue
        if cn == "FunctionPortListSyntax":
            break
        if return_node is None:
            return_node = ch
        else:
            name_node = ch
            break
    name = ""
    if name_node is not None:
        if _cls(name_node) == "KeywordNameSyntax":
            for sub in name_node:
                if _is_token(sub) and _token_kind_name(sub) == "NewKeyword":
                    name = "new"
                    break
        if not name:
            toks = _identifier_tokens(name_node)
            if toks:
                name = toks[0].valueText
    return_type: str | None = None
    if return_node is not None:
        cn = _cls(return_node)
        if cn == "ImplicitTypeSyntax":
            return_type = None
        elif cn == "KeywordTypeSyntax":
            for sub in return_node:
                if _is_token(sub):
                    return_type = sub.valueText
                    break
        else:
            return_type = _expression_text(return_node)
    return name, return_type


def _class_property_declarators(prop_node: Any) -> list[Any]:
    """Return the list of DeclaratorSyntax children belonging to a
    ClassPropertyDeclarationSyntax.

    The property declaration wraps an inner declaration (DataDeclaration or
    ParameterDeclaration); the declarators live under a SeparatedList child
    of that inner declaration.
    """
    inner = None
    for ch in prop_node:
        if _is_token(ch):
            continue
        cn = _cls(ch)
        if cn in {"DataDeclarationSyntax", "ParameterDeclarationStatementSyntax",
                  "TypedefDeclarationSyntax"}:
            inner = ch
            break
    if inner is None:
        return []
    out: list[Any] = []
    for ch in inner:
        if _is_token(ch):
            continue
        # SeparatedList wrapper.
        try:
            kids = list(ch)
        except TypeError:
            continue
        for sub in kids:
            if _is_token(sub):
                continue
            if _cls(sub) == "DeclaratorSyntax":
                out.append(sub)
    return out


def _checker_name_of(chk_syn: Any) -> str:
    """Return the checker name from a CheckerDeclarationSyntax.

    Grammar: ``checker <Identifier> [( <ports> )] ; <items> endchecker``.
    The checker name is the first direct Identifier Token child following
    the ``CheckerKeyword`` token. Walking direct children only avoids
    descending into the body where Identifier tokens refer to signals.
    """
    saw_checker_kw = False
    for ch in chk_syn:
        if _is_token(ch):
            kind = _token_kind_name(ch)
            if kind == "CheckerKeyword":
                saw_checker_kw = True
                continue
            if saw_checker_kw and kind == "Identifier":
                return ch.valueText
    return ""


def _checker_instantiation_type_name(ci_syn: Any) -> str:
    """Return the checker-type identifier from a CheckerInstantiationSyntax.

    Grammar: ``<CheckerType> <inst_name> ( <connections> ) ;``. The type
    name is the first Identifier-bearing direct child. We probe direct
    Identifier tokens first, then walk one level into the first non-token
    child looking for an identifier (mirrors how ``rule_s6`` resolves
    HierarchyInstantiation type names).
    """
    for ch in ci_syn:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier":
            return ch.valueText
    for ch in ci_syn:
        if _is_token(ch):
            continue
        toks = _identifier_tokens(ch)
        if toks:
            return toks[0].valueText
    return ""


def _checker_instance_name(ci_syn: Any) -> str:
    """Return the instance-name identifier from a CheckerInstantiationSyntax.

    The instance name lives inside an ``InstanceNameSyntax`` direct child
    (or the first Identifier token under it). Returns ``""`` if absent.
    """
    for ch in ci_syn:
        if _is_token(ch):
            continue
        if _cls(ch) == "InstanceNameSyntax":
            toks = _identifier_tokens(ch)
            if toks:
                return toks[0].valueText
            return ""
    return ""


def _extern_decl_kind_of(ext_syn: Any) -> str:
    """Return ``"module" | "interface" | "program"`` for an
    ExternModuleDeclSyntax based on its ``header.kind``.

    pyslang reuses ``SyntaxKind.ExternModuleDecl`` for all three forms; the
    discriminator is the header child whose kind is one of ``ModuleHeader``,
    ``InterfaceHeader``, ``ProgramHeader``. If the header is somehow absent
    or unrecognised we return ``"module"`` as the safest default — the LRM
    grammar guarantees one of the three is present in any parseable extern
    declaration.
    """
    hdr = getattr(ext_syn, "header", None)
    if hdr is None:
        return "module"
    kname = str(getattr(hdr, "kind", "")).rsplit(".", 1)[-1]
    if kname == "InterfaceHeader":
        return "interface"
    if kname == "ProgramHeader":
        return "program"
    return "module"


def _extern_decl_name_of(ext_syn: Any) -> str:
    """Return the declared name from an ExternModuleDeclSyntax.

    Grammar: ``extern (module|interface|program) <Identifier> [#(params)]
    [(ports)] ;``. The name is the first Identifier Token under the header
    (the header keyword precedes it). We walk only the header's direct
    children to avoid descending into the parameter / port lists where
    Identifier tokens refer to parameter / port names.
    """
    hdr = getattr(ext_syn, "header", None)
    if hdr is None:
        return ""
    saw_kw = False
    for ch in hdr:
        if _is_token(ch):
            kn = _token_kind_name(ch)
            if kn in {"ModuleKeyword", "InterfaceKeyword", "ProgramKeyword"}:
                saw_kw = True
                continue
            if saw_kw and kn == "Identifier":
                return ch.valueText
    # Fallback: first identifier anywhere under the header.
    toks = _identifier_tokens(hdr)
    return toks[0].valueText if toks else ""


def _extern_decl_ports(ext_syn: Any) -> list[str]:
    """Return the ordered list of port names from an ExternModuleDeclSyntax.

    Walks the header's AnsiPortList (or NonAnsiPortList) direct child and
    extracts the first Identifier token under each ImplicitAnsiPort /
    ExplicitAnsiPort / port-decl entry. Returns an empty list when the
    header has no port list (zero-arg form ``extern program ext_prog ();``
    actually has an empty AnsiPortList — we return ``[]`` for that case).
    """
    hdr = getattr(ext_syn, "header", None)
    if hdr is None:
        return []
    out: list[str] = []
    for ch in hdr:
        if _is_token(ch):
            continue
        cn = _cls(ch)
        if cn not in {"AnsiPortListSyntax", "NonAnsiPortListSyntax"}:
            continue
        # The port-list wraps a SeparatedList of port-syntax entries; we
        # walk two levels to reach each port (level 1 = SeparatedList /
        # token, level 2 = the *PortSyntax entries themselves).
        port_entries: list[Any] = []
        for sub in ch:
            if _is_token(sub):
                continue
            sub_cls = _cls(sub)
            if "Port" in sub_cls:
                port_entries.append(sub)
                continue
            # SeparatedList wrapper — descend one more level.
            for g in sub:
                if _is_token(g):
                    continue
                if "Port" in _cls(g):
                    port_entries.append(g)
        for sub in port_entries:
            # Prefer the DeclaratorSyntax's identifier (skips type idents).
            decl = next(
                (g for g in sub if not _is_token(g)
                 and _cls(g) == "DeclaratorSyntax"),
                None,
            )
            if decl is not None:
                ids = _identifier_tokens(decl)
                if ids:
                    out.append(ids[0].valueText)
                    continue
            ids = _identifier_tokens(sub)
            if ids:
                out.append(ids[0].valueText)
    return out


def _typedef_name_of(td_syn: Any) -> str:
    """The user-given name token of a TypedefDeclarationSyntax — the LAST
    direct Identifier Token child."""
    last_id = ""
    for ch in td_syn:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier":
            last_id = ch.valueText
    return last_id


def _struct_union_body_of(td_syn: Any) -> Any | None:
    """Return the StructUnionTypeSyntax direct child of a TypedefDeclaration,
    or None if the typedef body is not a struct/union.

    pyslang surfaces both ``struct`` and ``union`` bodies with the SAME class
    ``StructUnionTypeSyntax``; the variant is on ``.kind`` (StructType /
    UnionType). Callers discriminate via ``str(body.kind).rsplit('.', 1)[-1]``.
    """
    for ch in td_syn:
        if _is_token(ch):
            continue
        if _cls(ch) == "StructUnionTypeSyntax":
            return ch
    return None


def _struct_union_modifiers_of(body_syn: Any) -> dict[str, bool]:
    """Detect ``packed`` / ``tagged`` modifiers on a StructUnionTypeSyntax by
    walking its direct-child Token list. No regex on source text — both
    keywords surface as dedicated Token kinds (``PackedKeyword`` /
    ``TaggedKeyword``) immediately after the leading struct/union keyword.
    """
    packed = False
    tagged = False
    for ch in body_syn:
        if not _is_token(ch):
            continue
        kn = _token_kind_name(ch)
        if kn == "PackedKeyword":
            packed = True
        elif kn == "TaggedKeyword":
            tagged = True
    return {"packed": packed, "tagged": tagged}


def _type_text_of(type_syn: Any) -> str:
    """Concatenate the raw token text of a type node (whitespace-separated).

    Used to surface a light, human-readable type fingerprint for struct/union
    members without lifting the full type subtree. Walks tokens in document
    order; collapses runs of whitespace to single spaces.
    """
    if type_syn is None:
        return ""
    parts: list[str] = []

    def _walk(n: Any) -> None:
        if _is_token(n):
            txt = getattr(n, "valueText", "") or ""
            if txt:
                parts.append(txt)
            return
        try:
            kids = list(n)
        except TypeError:
            return
        for c in kids:
            _walk(c)

    _walk(type_syn)
    return " ".join(parts)


def _struct_union_members_of(body_syn: Any) -> list[dict[str, str]]:
    """Light scan of struct/union members from a StructUnionTypeSyntax.

    Each direct ``StructUnionMemberSyntax`` child carries a single type node
    followed by a SeparatedList of DeclaratorSyntax names (``logic [7:0] a, b;``
    yields two entries with the same type_text). We emit one
    ``{"name", "type_text"}`` dict per declarator. The type node is the FIRST
    non-token, non-SyntaxList, non-SeparatedList child of the member — this
    matches both IntegerTypeSyntax (``logic [7:0]``) and NamedTypeSyntax
    (``my_t``) without depending on a specific class name.
    """
    out: list[dict[str, str]] = []
    if body_syn is None:
        return out
    # The StructUnionMember entries live inside a SyntaxList wrapper that
    # pyslang surfaces with class name "SyntaxNode" (not "SyntaxList") — its
    # discriminator is on ``.kind``. We just collect every direct grandchild
    # of class StructUnionMemberSyntax, which is robust to either layout.
    member_nodes: list[Any] = []
    for ch in body_syn:
        if _is_token(ch):
            continue
        if _cls(ch) == "StructUnionMemberSyntax":
            member_nodes.append(ch)
            continue
        try:
            sub_kids = list(ch)
        except TypeError:
            continue
        for sub in sub_kids:
            if not _is_token(sub) and _cls(sub) == "StructUnionMemberSyntax":
                member_nodes.append(sub)
    for mem in member_nodes:
        # Walk direct children. Discriminate via ``.kind`` (not class name)
        # because pyslang surfaces SyntaxList / SeparatedList wrappers with
        # the generic ``SyntaxNode`` class — only the kind enum tags them.
        type_node = None
        decl_list = None
        for sub in mem:
            if _is_token(sub):
                continue
            sub_kind = str(getattr(sub, "kind", "")).rsplit(".", 1)[-1]
            if sub_kind == "SyntaxList":
                continue
            if sub_kind == "SeparatedList":
                decl_list = sub
                continue
            if type_node is None:
                type_node = sub
        type_text = _type_text_of(type_node)
        search_root = decl_list if decl_list is not None else mem
        try:
            decl_kids = list(search_root)
        except TypeError:
            decl_kids = []
        for d in decl_kids:
            if _is_token(d) or _cls(d) != "DeclaratorSyntax":
                continue
            ids = _identifier_tokens(d)
            if ids:
                out.append({"name": ids[0].valueText,
                            "type_text": type_text})
    return out


def _forward_typedef_name_of(fwd_syn: Any) -> str:
    """Return the forward-typedef name token. ForwardTypedefDeclarationSyntax
    has a single Identifier direct child (the forward name)."""
    for ch in fwd_syn:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier":
            return ch.valueText
    return ""


def _enum_value_names(enum_syn: Any) -> list[str]:
    """Value-declarator names under an EnumTypeSyntax."""
    def _descendants_local(n: Any):
        yield n
        if _is_token(n):
            return
        try:
            kids = list(n)
        except TypeError:
            return
        for c in kids:
            yield from _descendants_local(c)

    out: list[str] = []
    for d in _descendants_local(enum_syn):
        if _cls(d) != "DeclaratorSyntax":
            continue
        toks = _identifier_tokens(d)
        if toks:
            out.append(toks[0].valueText)
    return out


def _dpi_export_name_of(node: Any) -> str:
    """Return the declared SV function/task name from a ``DPIExportSyntax`` node.

    Structure: ``export <StringLiteral> (function|task) <Identifier> ;``.
    pyslang surfaces a named ``.name`` attribute on ``DPIExportSyntax`` that
    holds the single Identifier token — the SV function/task being exported.
    Falls back to scanning direct-child Identifier tokens for robustness.
    No regex on source text.
    """
    name_tok = getattr(node, "name", None)
    if name_tok is not None and _is_token(name_tok):
        val = getattr(name_tok, "valueText", "")
        if val:
            return val
    # Fallback: first direct Identifier token.
    for ch in node:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier":
            return ch.valueText
    return ""


def _dpi_export_spec_and_kind(node: Any) -> tuple[str, str]:
    """Return (spec, export_kind) from a ``DPIExportSyntax`` node.

    spec        — the DPI string literal value, e.g. "DPI-C" or "DPI",
                  with surrounding double-quotes stripped.
    export_kind — "function" or "task" derived from the leading keyword
                  token following the spec string.

    Both values are extracted structurally from token kinds and values —
    no regex on source text.
    """
    spec = ""
    export_kind = "function"
    # DPIExportSyntax has named attributes: specString, functionOrTask.
    spec_tok = getattr(node, "specString", None)
    if spec_tok is not None and _is_token(spec_tok):
        raw = getattr(spec_tok, "valueText", "")
        spec = raw.strip('"')
    ft_tok = getattr(node, "functionOrTask", None)
    if ft_tok is not None and _is_token(ft_tok):
        kn = _token_kind_name(ft_tok)
        if kn == "TaskKeyword":
            export_kind = "task"
    if not spec:
        # Fallback: scan direct tokens.
        for ch in node:
            if not _is_token(ch):
                continue
            tk = _token_kind_name(ch)
            if tk == "StringLiteral":
                raw = getattr(ch, "valueText", "")
                spec = raw.strip('"')
            elif tk == "TaskKeyword":
                export_kind = "task"
            elif tk == "FunctionKeyword":
                export_kind = "function"
    return spec, export_kind


def _dpi_import_name_of(node: Any) -> str:
    """Return the declared SV function/task name from a ``DPIImportSyntax`` node.

    Structure: DPIImportSyntax → FunctionPrototypeSyntax → IdentifierNameSyntax
    → Identifier token.  The function/task name is the first Identifier token
    inside the FunctionPrototypeSyntax child — structurally, the IdentifierName
    child of the prototype.  No regex on source text.
    """
    for ch in node:
        if ch is None or _is_token(ch):
            continue
        if _cls(ch) == "FunctionPrototypeSyntax":
            for gch in ch:
                if gch is None or _is_token(gch):
                    continue
                if _cls(gch) == "IdentifierNameSyntax":
                    toks = _identifier_tokens(gch)
                    if toks:
                        return toks[0].valueText
            break
    return ""


def _dpi_import_spec_and_kind(node: Any) -> tuple[str, str]:
    """Return (spec, import_kind) from a ``DPIImportSyntax`` node.

    spec       — the DPI string literal value, e.g. "DPI-C" or "DPI",
                 with surrounding quotes stripped.
    import_kind — "function" or "task" derived from the leading keyword
                  token inside FunctionPrototypeSyntax.

    Both values are extracted structurally from token kinds and values —
    no regex on source text.
    """
    spec = ""
    import_kind = "function"
    for ch in node:
        if ch is None:
            continue
        if _is_token(ch):
            tk = _token_kind_name(ch)
            if tk == "StringLiteral":
                # valueText includes the surrounding double-quotes; strip them.
                raw = ch.valueText
                spec = raw.strip('"')
        else:
            if _cls(ch) == "FunctionPrototypeSyntax":
                for gch in ch:
                    if gch is None or not _is_token(gch):
                        continue
                    tk2 = _token_kind_name(gch)
                    if tk2 == "FunctionKeyword":
                        import_kind = "function"
                        break
                    if tk2 == "TaskKeyword":
                        import_kind = "task"
                        break
    return spec, import_kind
