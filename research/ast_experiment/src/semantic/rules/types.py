"""Type rules — S9 (Package, Typedef, Enum), S31 (Struct/Union/Forward),
S32 (PackageImport/Export), S48 (TypeParameterDeclaration),
S50 (PackageImportItem), S51 (PackageExportAllDeclaration), and
S53 (NetTypeDeclaration).

The actual promotion of typedef-shaped nodes lives in dispatch.promote's
pass 1 (declarative tree walk). The metadata entries below pin the rule_id
under each pyslang kind so the bucket1 checklist derives correctly.

S31 extends the S9 TypedefDeclaration promotion with struct/union body
attributes (body_kind, packed, tagged, members) when the typedef wraps a
``StructUnionTypeSyntax`` child. ``StructType`` and ``UnionType`` therefore
have no independent semantic identity — they enrich the surrounding typedef
node and are registered here only so the bucket1 derivation flips them to
Sem ✅. The bare ``typedef <name>;`` form (``ForwardTypedefDeclaration``)
gets its OWN node with role=typedef_forward, attached to its enclosing
scope via a ``has_typedef`` edge (same edge type as a full typedef so
existing queries — e.g. ``neighbors(pkg, edge_type='has_typedef')`` —
return both full and forward declarations uniformly).

S48 promotes ``TypeParameterDeclaration`` (``parameter type T = int;``).
A single declaration may carry multiple ``TypeAssignment`` children
(``parameter type A = int, B = bit;``); each assignment becomes a separate
queryable node with role=type_param, a ``has_type_param`` edge from the
enclosing scope (module or class), and an optional ``default_type`` attribute
(absent when no default is specified, e.g. ``parameter type T;``). Path key
is ``<scope>.<name>`` where scope comes from class_stack (class context) or
module_stack (module / package context). Names are registered in the shared
semantic_name_index for cross-file resolution.
"""

from __future__ import annotations

import pyslang

from ..common.graph import _add_edge
from ..common.tokens import _package_import_item_parts


def _s9a_package(*args, **kwargs):
    return


def _s9b_typedef(*args, **kwargs):
    return


def _s9c_enum_type(*args, **kwargs):
    return


def _s31_struct_type(*args, **kwargs):
    return


def _s31_union_type(*args, **kwargs):
    return


def _s31_forward_typedef(*args, **kwargs):
    return


def _s32_package_import(*args, **kwargs):
    return


def _s32_package_export(*args, **kwargs):
    return


def _s48_type_parameter_declaration(*args, **kwargs):
    return


def rule_s50(graph, node, gid, gnode, scope, name_index, leaks, scope_path="",
             module_gid=None, **_):
    """S50 — PackageImportItem → granular ``imports_item`` edge per item.

    Strategy (B): S32 keeps its existing per-decl ``imports`` edges for
    backward compatibility. S50 adds a finer-grained ``imports_item`` edge
    for each individual ``PackageImportItemSyntax`` node, allowing queries
    that distinguish ``import pkg_a::foo`` from ``import pkg_b::bar`` inside
    the same declaration without iterating the S32 ``imports`` edge payload.

    Edge shape:
      src  = enclosing module / package gid (module_stack top, passed as
             ``module_gid`` by the dispatch shim — same pattern as S6/S33)
      dst  = package node gid (or ``_unresolved.<pkg>`` with unresolved=True)
      type = "imports_item"
      payload = {"package": <pkg_name>, "symbol": <name_or_"*">}

    Resolution follows S32 convention: ``package:<name>`` key first, then
    bare name. Compilation-unit-scope items (no enclosing scope, i.e.
    ``module_gid is None``) are skipped and appended to ``semantic_leaks``.
    """
    parts = _package_import_item_parts(node)
    if parts is None:
        return
    pkg_name, symbol = parts

    if module_gid is None:
        graph.setdefault("semantic_leaks", []).append({
            "kind": "PackageImportItem",
            "reason": "cu-scope PackageImportItem skipped",
            "package": pkg_name,
            "symbol": symbol,
        })
        return

    # Resolve target package node (mirrors S32 resolution convention).
    tgt_id = name_index.get(f"package:{pkg_name}") or name_index.get(pkg_name)
    unresolved = False
    if tgt_id is None:
        tgt_id = f"_unresolved.{pkg_name}"
        unresolved = True

    payload = {"package": pkg_name, "symbol": symbol}
    if unresolved:
        payload["unresolved"] = True
    _add_edge(graph, module_gid, tgt_id, "imports_item", **payload)


def _s50_stub(*args, **kwargs):
    return


def rule_s51(graph, node, gid, gnode, scope, name_index, leaks, scope_path="",
             module_gid=None, **_):
    """S51 — PackageExportAllDeclaration → ``exports_all`` self-loop edge.

    ``export *::*;`` re-exports every symbol imported from any package.  There
    is no specific target package; the enclosing scope re-exports everything.
    Representation: a single ``exports_all`` self-loop from the enclosing
    package / module node to itself, with payload ``{"wildcard": True}``.

    Edge shape:
      src  = enclosing module / package gid (module_stack top, passed as
             ``module_gid`` by the dispatch shim — same pattern as S50)
      dst  = same gid (self-loop)
      type = "exports_all"
      payload = {"wildcard": True}

    Compilation-unit-scope occurrences (``module_gid is None``) are skipped
    and appended to ``semantic_leaks`` — consistent with S32/S50 convention.
    """
    if module_gid is None:
        graph.setdefault("semantic_leaks", []).append({
            "kind": "PackageExportAllDeclaration",
            "reason": "cu-scope export *::* skipped",
        })
        return

    _add_edge(graph, module_gid, module_gid, "exports_all", wildcard=True)


def _s51_stub(*args, **kwargs):
    return


def rule_s53(graph, node, gid, gnode, scope, name_index, leaks, scope_path="",
             module_gid=None, **_):
    """S53 — NetTypeDeclaration → node with role=nettype + ``has_nettype`` edge.

    ``nettype DATA_T my_net_t;`` / ``nettype DATA_T my_net_t with resolver;``
    (SV §6.6.7 user-defined net types).

    Node attributes:
      data_type  — whitespace-joined token text of the data-type child node
                   (everything between the ``nettype`` keyword and the name
                   identifier).
      resolver   — identifier string from the ``with <func>`` clause, or None
                   when no resolver is specified.

    Edge shape:
      src  = enclosing module / package gid (passed as ``module_gid``)
      dst  = this nettype node gid
      type = "has_nettype"

    If ``resolver`` resolves in name_index, an additional
    ``nettype_resolved_by`` edge is emitted from the nettype node to the
    resolver function node.

    The nettype name is registered in name_index as ``<scope>.<name>`` so
    downstream net declarations using this nettype can resolve it.

    Compilation-unit-scope nettypes (``module_gid is None``) are skipped and
    recorded in ``semantic_leaks`` — consistent with S50/S51 convention.
    """
    from ..common.tokens import _cls, _is_token, _token_kind_name

    if module_gid is None:
        graph.setdefault("semantic_leaks", []).append({
            "kind": "NetTypeDeclaration",
            "reason": "cu-scope NetTypeDeclaration skipped",
        })
        return

    # Walk direct children to extract name, data_type tokens, and resolver.
    # Layout: [SyntaxList] NetTypeKeyword <type_syntax> Identifier
    #         [WithFunctionClauseSyntax] Semicolon
    nettype_name = ""
    data_type_tokens: list[str] = []
    resolver_name: str | None = None
    saw_keyword = False
    saw_type = False  # True after we've passed the first non-keyword syntax node

    for ch in node:
        if ch is None:
            continue
        if _is_token(ch):
            tok_kind = _token_kind_name(ch)
            if tok_kind == "NetTypeKeyword":
                saw_keyword = True
                continue
            if tok_kind in {"Semicolon"}:
                continue
            if tok_kind == "Identifier" and saw_keyword and saw_type:
                # Name identifier comes AFTER the data-type syntax node.
                nettype_name = ch.valueText
            elif saw_keyword and not saw_type:
                # Keyword token that is part of the data type (shouldn't happen
                # for common cases where the type is a syntax node, but guard
                # for scalar primitive types).
                v = ch.valueText
                if v:
                    data_type_tokens.append(v)
        else:
            cn = _cls(ch)
            if cn == "SyntaxNode" and not saw_keyword:
                # Leading attribute SyntaxList — skip
                continue
            if cn == "WithFunctionClauseSyntax":
                # ``with <func>`` clause — extract the identifier inside
                for wch in ch:
                    if wch is None:
                        continue
                    if _is_token(wch):
                        if _token_kind_name(wch) == "WithKeyword":
                            continue
                        v = wch.valueText
                        if v:
                            resolver_name = v
                    else:
                        # IdentifierNameSyntax wrapping the identifier token
                        for iwch in wch:
                            if iwch is None:
                                continue
                            if _is_token(iwch) and _token_kind_name(iwch) == "Identifier":
                                resolver_name = iwch.valueText
            elif saw_keyword and not saw_type:
                # This is the data-type syntax node — collect all tokens
                def _collect_tokens(n: object, out: list) -> None:  # type: ignore[type-arg]
                    try:
                        for t in n:  # type: ignore[union-attr]
                            if t is None:
                                continue
                            if _is_token(t):
                                v = t.valueText
                                if v:
                                    out.append(v)
                            else:
                                _collect_tokens(t, out)
                    except TypeError:
                        pass
                _collect_tokens(ch, data_type_tokens)
                saw_type = True

    if not nettype_name:
        return

    data_type_str = " ".join(data_type_tokens) if data_type_tokens else ""
    net_path = f"{scope_path}.{nettype_name}" if scope_path else nettype_name

    # Derive scope_path from module_gid via reverse lookup in name_index when
    # scope_path is empty (shouldn't happen in practice but be defensive).
    if not scope_path:
        rev = {v: k for k, v in name_index.items()}
        scope_path = rev.get(module_gid, "")
        net_path = f"{scope_path}.{nettype_name}" if scope_path else nettype_name

    attrs: dict = {"data_type": data_type_str, "resolver": resolver_name}
    gnode["semantic"] = {
        "rule_id": "S53",
        "role": "nettype",
        "name": nettype_name,
        "path": net_path,
        "attributes": attrs,
    }

    _add_edge(graph, module_gid, gid, "has_nettype")
    name_index[net_path] = gid

    # Optional nettype_resolved_by edge when the resolver is in name_index.
    if resolver_name is not None:
        resolver_gid = name_index.get(resolver_name) or name_index.get(
            f"{scope_path}.{resolver_name}"
        )
        if resolver_gid is not None:
            _add_edge(graph, gid, resolver_gid, "nettype_resolved_by")


_s9a_package.__rule_id__ = "S9a"
_s9b_typedef.__rule_id__ = "S9b"
_s9c_enum_type.__rule_id__ = "S9c"
_s31_struct_type.__rule_id__ = "S31"
_s31_union_type.__rule_id__ = "S31"
_s31_forward_typedef.__rule_id__ = "S31"
_s32_package_import.__rule_id__ = "S32"
_s32_package_export.__rule_id__ = "S32"
_s48_type_parameter_declaration.__rule_id__ = "S48"
rule_s50.__rule_id__ = "S50"
_s50_stub.__rule_id__ = "S50"
rule_s51.__rule_id__ = "S51"
_s51_stub.__rule_id__ = "S51"
rule_s53.__rule_id__ = "S53"


def _s58_struct_union_member(*args, **kwargs):
    """S58 — StructUnionMember promotion ownership marker.

    The actual fan-out runs in ``dispatch.promote`` pass 1 — for each
    StructUnionMember row inside a struct/union-bodied typedef, one
    ``role=struct_member`` / ``role=union_member`` node is emitted per
    Declarator (so ``logic [3:0] a, b;`` becomes two nodes) and attached
    to the enclosing typedef via a ``has_member`` edge. Per-node attrs:
    ``{data_type, parent_kind: "struct"|"union"}``; path key:
    ``<typedef_path>.<field_name>``.

    Anonymous inline struct / union types (no enclosing typedef) leave
    the struct_union_stack empty, so members in those positions are
    silently left BLOB — only typedef-fronted bodies promote.
    """
    return


_s58_struct_union_member.__rule_id__ = "S58"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.PackageDeclaration, _s9a_package),
    (pyslang.SyntaxKind.TypedefDeclaration, _s9b_typedef),
    (pyslang.SyntaxKind.EnumType, _s9c_enum_type),
    (pyslang.SyntaxKind.StructType, _s31_struct_type),
    (pyslang.SyntaxKind.UnionType, _s31_union_type),
    (pyslang.SyntaxKind.ForwardTypedefDeclaration, _s31_forward_typedef),
    (pyslang.SyntaxKind.PackageImportDeclaration, _s32_package_import),
    (pyslang.SyntaxKind.PackageExportDeclaration, _s32_package_export),
    (pyslang.SyntaxKind.TypeParameterDeclaration, _s48_type_parameter_declaration),
    (pyslang.SyntaxKind.PackageImportItem, rule_s50),
    (pyslang.SyntaxKind.PackageExportAllDeclaration, rule_s51),
    (pyslang.SyntaxKind.NetTypeDeclaration, rule_s53),
    (pyslang.SyntaxKind.StructUnionMember, _s58_struct_union_member),
]
