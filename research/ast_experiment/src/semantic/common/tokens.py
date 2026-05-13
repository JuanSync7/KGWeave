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
