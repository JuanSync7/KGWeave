"""Type rules — S9 (Package, Typedef, Enum), S31 (Struct/Union/Forward),
S32 (PackageImport/Export), S48 (TypeParameterDeclaration), and
S50 (PackageImportItem).

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
]
