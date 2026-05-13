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


def _typedef_name_of(td_syn: Any) -> str:
    """The user-given name token of a TypedefDeclarationSyntax — the LAST
    direct Identifier Token child."""
    last_id = ""
    for ch in td_syn:
        if _is_token(ch) and _token_kind_name(ch) == "Identifier":
            last_id = ch.valueText
    return last_id


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
