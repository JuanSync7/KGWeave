"""Type rules — S9 (Package, Typedef, Enum), S31 (Struct/Union/Forward),
S32 (PackageImport/Export), and S48 (TypeParameterDeclaration).

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


_s9a_package.__rule_id__ = "S9a"
_s9b_typedef.__rule_id__ = "S9b"
_s9c_enum_type.__rule_id__ = "S9c"
_s31_struct_type.__rule_id__ = "S31"
_s31_union_type.__rule_id__ = "S31"
_s31_forward_typedef.__rule_id__ = "S31"
_s32_package_import.__rule_id__ = "S32"
_s32_package_export.__rule_id__ = "S32"
_s48_type_parameter_declaration.__rule_id__ = "S48"


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
]
