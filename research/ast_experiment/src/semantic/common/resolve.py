"""Symbol resolution helpers — wrappers over pyslang Compilation lookup
with name-string fallback."""

from __future__ import annotations

from typing import Any


def _module_scope(compilation: Any) -> Any:
    """Legacy: return the FIRST top instance body. Retained for back-compat;
    multi-module callers should iterate ``_all_module_scopes``."""
    top = list(compilation.getRoot().topInstances)
    if not top:
        return None
    return top[0].body


def _all_module_scopes(compilation: Any) -> list[Any]:
    """Return every elaborated ``InstanceBodySymbol`` in the compilation."""
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
    """Hierarchical path for an elaborated scope."""
    if scope is None:
        return ""
    for attr in ("hierarchicalPath",):
        try:
            v = getattr(scope, attr, None)
            if isinstance(v, str) and v:
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
    """Resolve ``name`` to a graph id; record a leak if we fall back."""
    sym = _lookup_name(scope, name)
    key = f"{scope_path}.{name}" if scope_path else name
    nid = name_index.get(key)
    if nid is None:
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
