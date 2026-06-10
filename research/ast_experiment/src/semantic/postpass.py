"""Global post-promotion sweeps — resolution that needs the FULLY populated
name_index (all files, all passes done), so it can't run inside per-tree
dispatch without pass-ordering hazards.

``resolve_of_type`` lifts the ``of_type`` edge (signal → its user-defined type
node). It runs once over the whole graph after ``build_kg``'s pass2, operating
purely on the lifted graph dict (no pyslang), so cross-file / cross-pass
ordering is irrelevant.

Scope (this increment): **ports**. A port's declared type lives in its header
subtree, directly reachable from the port node via ``child`` edges. Nets and
params carry their type as a *sibling* of the declarator (needs parent lookup)
and are a documented follow-up.
"""

from __future__ import annotations

from typing import Any

from .common.graph import _add_edge, _has_edge
from .queries import find_by_name

# Type-bearing syntactic wrappers we descend through to reach the NamedType.
_TYPE_NAME_CLS = "NamedTypeSyntax"

# Subtrees skipped when collecting an assertion's checked-signal identifiers:
# the assertion's own label, and the sampling-clock event (``@(posedge clk)``)
# which is the ``sensitive_to`` relation, not a checked data signal.
_CHECKS_SKIP_EXACT = "NamedLabelSyntax"
_CHECKS_SKIP_SUBSTR = "EventControl"


def _children_index(graph: dict[str, Any]) -> dict[str, list[str]]:
    ch: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e["type"] == "child":
            ch.setdefault(e["src"], []).append(e["dst"])
    return ch


# Roles whose declared type is a *sibling* of the declarator (a direct child
# of the enclosing DataDeclaration / ParameterDeclaration), not a descendant.
_SIBLING_TYPE_ROLES = {"net", "param"}


def _first_identifier(root_id: str, by_id: dict[str, Any],
                      ch: dict[str, list[str]]) -> str | None:
    """First Identifier-token value at/under ``root_id`` (breadth-first)."""
    stack = [root_id]
    while stack:
        m = by_id.get(stack.pop(0))
        if m is None:
            continue
        if (m.get("is_token")
                and str(m.get("kind", "")).split(".")[-1] == "Identifier"):
            return (m.get("payload", {}) or {}).get("valueText")
        stack.extend(ch.get(m["id"], []))
    return None


_SCOPED_NAME_CLS = "ScopedNameSyntax"
_IDENT_NAME_CLS = "IdentifierNameSyntax"


def _type_name_from_named_type(nt_id: str, by_id: dict[str, Any],
                               ch: dict[str, list[str]]) -> str | None:
    """The user-defined type name carried by a ``NamedTypeSyntax`` node.

    * Bare type (``my_t``)         → ``"my_t"``.
    * Package-scoped (``pkg::T``)  → ``"pkg.T"`` — the ScopedName segments
      joined with '.', so it resolves against the hierarchical name index
      (the type node is keyed ``pkg.T``). The type is the LAST segment; a
      plain first-identifier scan would wrongly return the package.
    """
    for cid in ch.get(nt_id, []):
        c = by_id.get(cid)
        if c is None:
            continue
        ctype = str(c.get("type", ""))
        if ctype == _SCOPED_NAME_CLS:
            segs: list[str] = []
            for seg in ch.get(cid, []):
                if str((by_id.get(seg) or {}).get("type", "")) == _IDENT_NAME_CLS:
                    ident = _first_identifier(seg, by_id, ch)
                    if ident:
                        segs.append(ident)
            return ".".join(segs) if segs else None
        if ctype == _IDENT_NAME_CLS:
            return _first_identifier(cid, by_id, ch)
    # Any other wrapper shape (e.g. parameterised type): fall back to the
    # first identifier anywhere in the subtree (prior behaviour, no regression).
    return _first_identifier(nt_id, by_id, ch)


def _named_type_name(root_id: str, by_id: dict[str, Any],
                     ch: dict[str, list[str]]) -> str | None:
    """First user-defined type name (``NamedTypeSyntax`` → identifier) anywhere
    under ``root_id`` — the PORT case (type lives in the port-header subtree).
    Returns None for built-in keyword types (no NamedType)."""
    stack = list(ch.get(root_id, []))
    while stack:
        nid = stack.pop(0)
        n = by_id.get(nid)
        if n is None:
            continue
        if str(n.get("type", "")) == _TYPE_NAME_CLS:
            return _type_name_from_named_type(nid, by_id, ch)
        stack.extend(ch.get(nid, []))
    return None


# Climbing the declarator's ancestors to find its declaration's type: a
# separated-list wrapper node sits between the declarator and the enclosing
# DataDeclaration / ParameterDeclaration, so the type is the declarator's
# *grandparent's* child — climb a few levels rather than assume one. Stop at a
# scope boundary so a built-in-typed declarator never picks up an outer type.
_OF_TYPE_CLIMB_MAX = 5
_SCOPE_STOP = {
    "ModuleDeclarationSyntax",   # module / interface / package / program
    "ClassDeclarationSyntax",
    "CheckerDeclarationSyntax",
}


def _sibling_type_via_ancestors(decl_id: str, by_id: dict[str, Any],
                                ch: dict[str, list[str]],
                                parent_of: dict[str, str]) -> str | None:
    """First ``NamedTypeSyntax`` among a declarator's enclosing declaration's
    DIRECT children — the NET/PARAM case (type is a declarator *sibling*, one
    list-wrapper level up). Climbs ancestors, returning on the first level that
    carries a NamedType among its direct children; stops at the scope boundary
    (built-in-typed declarator → None)."""
    nid = decl_id
    for _ in range(_OF_TYPE_CLIMB_MAX):
        pid = parent_of.get(nid)
        if pid is None:
            return None
        for cid in ch.get(pid, []):
            c = by_id.get(cid)
            if c is not None and str(c.get("type", "")) == _TYPE_NAME_CLS:
                return _type_name_from_named_type(cid, by_id, ch)
        if str((by_id.get(pid) or {}).get("type", "")) in _SCOPE_STOP:
            return None
        nid = pid
    return None


def resolve_of_type(graph: dict[str, Any]) -> None:
    """Emit ``of_type`` edges from typed signals to their type nodes.

    Two structural shapes:
      * ``port`` — type lives inside the port's own header subtree (descend).
      * ``net`` / ``param`` — type is a *sibling* of the declarator under the
        enclosing declaration (look up the parent, scan its direct children).

    Unresolvable user-defined types (forward ref / external) get an edge to a
    ``_unresolved.<name>`` sentinel with ``payload.unresolved=True``, mirroring
    the S25/S32 convention so downstream queries still see the dependency.
    """
    by_id = {n["id"]: n for n in graph["nodes"]}
    ch = _children_index(graph)
    parent_of: dict[str, str] = {}
    for e in graph["edges"]:
        if e["type"] == "child":
            parent_of[e["dst"]] = e["src"]
    for n in graph["nodes"]:
        sem = n.get("semantic", {})
        role = sem.get("role")
        if not n.get("queryable"):
            continue
        if role == "port":
            tname = _named_type_name(n["id"], by_id, ch)
        elif role in _SIBLING_TYPE_ROLES:
            tname = _sibling_type_via_ancestors(n["id"], by_id, ch, parent_of)
        else:
            continue
        if not tname:
            continue
        target = find_by_name(graph, tname)
        if target is not None:
            dst, payload = target["id"], {}
        else:
            dst, payload = f"_unresolved.{tname}", {"unresolved": True}
        if not _has_edge(graph, n["id"], dst, "of_type"):
            _add_edge(graph, n["id"], dst, "of_type", **payload)


def _assertion_signal_names(root_id: str, by_id: dict[str, Any],
                            ch: dict[str, list[str]]) -> list[str]:
    """Identifier-token values under an assertion node, in first-seen order,
    excluding the assertion's own label and the sampling-clock event subtree.

    Structural-only: discriminates on node ``type`` and token ``kind``; never
    inspects raw source text (no regex — CLAUDE.md invariant 4).
    """
    out: list[str] = []
    stack = list(ch.get(root_id, []))
    while stack:
        nid = stack.pop(0)
        n = by_id.get(nid)
        if n is None:
            continue
        t = str(n.get("type", ""))
        if t == _CHECKS_SKIP_EXACT or _CHECKS_SKIP_SUBSTR in t:
            continue  # skip the whole label / clocking-event subtree
        if (n.get("is_token")
                and str(n.get("kind", "")).split(".")[-1] == "Identifier"):
            v = (n.get("payload", {}) or {}).get("valueText")
            if v:
                out.append(v)
            continue
        stack.extend(ch.get(nid, []))
    return out


def resolve_assertion_checks(graph: dict[str, Any]) -> None:
    """Emit ``checks`` edges from each assertion to the signals it constrains.

    An assertion is an *observer*: a separate ``checks`` edge (rather than
    reusing ``reads``) keeps the functional dataflow graph clean — assertions
    must not appear inside ``cone_of_influence`` / reverse-``reads`` results.

    Resolution mirrors S39's disable-expression ``reads``: each identifier is
    resolved scope-qualified-first (``<module>.<name>``) then by unambiguous
    bare name. Identifiers that bind to nothing (system funcs, keywords) emit
    no edge — unlike ``of_type``, there is no ``_unresolved`` sentinel here,
    because not every identifier in a property expression is a signal.
    """
    by_id = {n["id"]: n for n in graph["nodes"]}
    ch = _children_index(graph)
    idx = graph.get("semantic_name_index", {})
    for n in graph["nodes"]:
        sem = n.get("semantic", {})
        if not n.get("queryable") or sem.get("role") != "assertion":
            continue
        path = sem.get("path") or ""
        scope = path.rsplit(".", 1)[0] if "." in path else ""
        seen: set[str] = set()
        for name in _assertion_signal_names(n["id"], by_id, ch):
            if name in seen:
                continue
            seen.add(name)
            tgt_id = idx.get(f"{scope}.{name}") if scope else None
            target = by_id.get(tgt_id) if tgt_id else find_by_name(graph, name)
            if target is None or target["id"] == n["id"]:
                continue  # unresolved (skip, no noise) or self-reference
            if not _has_edge(graph, n["id"], target["id"], "checks"):
                _add_edge(graph, n["id"], target["id"], "checks", name=name)
