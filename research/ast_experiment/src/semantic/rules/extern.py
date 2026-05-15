"""S29 — Extern module / interface / program declarations.

S30 — Full ``program ... endprogram`` body promotion. SystemVerilog
``program`` blocks are LRM-typed testbench scopes that look like a module
for hierarchical-naming purposes but carry distinct semantics
(no always_*, restricted scheduling). pyslang surfaces a full program
body via the *shared* ``ModuleDeclarationSyntax`` class — the same class
used for ``module`` and ``interface`` and ``package``. The discriminator
is the node's ``.kind`` attribute, which takes the dedicated value
``SyntaxKind.ProgramDeclaration`` (distinct from
``SyntaxKind.ModuleDeclaration``).

S1 (in ``rules/structure.py``) owns the ``ModuleDeclaration`` SyntaxKind
and runs the shared ``ModuleDeclarationSyntax`` promotion branch in
``dispatch.promote`` pass-1. Because the branch dispatches on
``kind_name`` (PackageDeclaration / InterfaceDeclaration /
ProgramDeclaration / default → module), promoting a program body
correctly is purely a matter of:

* adding a ``ProgramDeclaration`` arm to the kind_name switch that
  stamps ``role="program"`` and emits ``has_program`` containment edges;
* pushing the program onto ``module_stack`` (same code path as modules)
  so child rules (S2 contains, S3/S8 always_* — though always_* is
  LRM-illegal inside a program — S10 functions, S14 properties, S16
  assertions, S18 clocking, S24 classes, S22 covergroups, ...) attach
  to the program via the standard ``_cur_module()`` lookup;
* registering ``ProgramDeclaration`` under a dedicated S30 ``__rule_id__``
  so the Bucket-1 PROMOTE_NOW counter reflects ownership and the
  registry-derived ACTIVE kinds list picks it up.

Note: the ``program`` kind is also one of the three discriminator values
inside S29's ExternModuleDecl — there ``program`` refers to the *extern
program* header (no body). S29 owns the header form; S30 owns the body
form. Both live in this file because they share the construct.

Future S-rules in this module:

* ``AnonymousProgram`` is also planned here.

S29 detail
----------

SystemVerilog ``extern module``, ``extern interface``, and ``extern program``
declarations are header-only: they declare the interface (name, parameters,
ports) without a body. The full module/interface/program definition lives
elsewhere in the compilation, typically in another file.

pyslang surfaces all three forms with a *single* shared syntax class
``ExternModuleDeclSyntax`` and a single ``SyntaxKind.ExternModuleDecl``
(204). The discriminator is the header child: ``ModuleHeader`` /
``InterfaceHeader`` / ``ProgramHeader``. The dispatch branch in pass 1 of
``dispatch.promote`` reads ``header.kind`` via ``_extern_decl_kind_of`` and
stamps the kind ("module" / "interface" / "program") as an attribute.

Promoted shape:

* role = ``extern_decl``
* attributes["kind"] ∈ {"module", "interface", "program"}
* attributes["ports"] = ordered list of port names (light token scan; full
  port types and directions stay BLOB on the underlying syntax node)
* path = ``<parent_or_root>.<name>`` — extern decls live at
  compilation-unit or package/module scope; for cu-scope decls the path is
  the bare declared name and no containment edge is emitted (mirrors how
  S24 handles cu-scope classes and S28 handles cu-scope checkers).
* Edge: ``(parent_or_root) -[has_extern_decl]-> (extern_decl_node)``
* Optional edge: ``(extern_decl) -[declares]-> (full_decl)`` — resolved
  against the shared ``semantic_name_index``. The full module / interface /
  program is registered under the bare name by S1, so the lookup succeeds
  when both the extern decl and the full body live in the same compilation
  (which is the common usage pattern for ``extern`` — the header lets
  downstream consumers see the contract before the body has been parsed).

The metadata stubs below pin ``__rule_id__="S29"`` against
``pyslang.SyntaxKind.ExternModuleDecl`` and ``__rule_id__="S30"`` against
``pyslang.SyntaxKind.ProgramDeclaration`` so the registry-derived Bucket-1
checklist counts both kinds as PROMOTE_NOW.
"""

from __future__ import annotations

import pyslang


def _s29_extern_module_decl(*args, **kwargs):
    """ExternModuleDecl is promoted in pass 1 of dispatch.promote — see the
    S29 branch. This stub exists only to register the SyntaxKind under an
    active ``__rule_id__`` for the Bucket-1 checklist. The three variants
    (extern module / extern interface / extern program) all share this kind
    and are discriminated at promotion time via ``header.kind``."""
    return


_s29_extern_module_decl.__rule_id__ = "S29"


def _s30_program_decl(*args, **kwargs):
    """ProgramDeclaration is promoted in pass 1 of dispatch.promote — see
    the shared ``ModuleDeclarationSyntax`` branch in S1, which dispatches
    on ``.kind`` and stamps ``role="program"`` + ``has_program`` for the
    ProgramDeclaration variant. This stub exists only to register the
    SyntaxKind under an active ``__rule_id__`` for the Bucket-1 checklist.
    Note that pyslang reuses ``ModuleDeclarationSyntax`` for module /
    interface / program / package bodies — only the dedicated
    ``SyntaxKind.ProgramDeclaration`` enum value distinguishes a program
    body at the kind level."""
    return


_s30_program_decl.__rule_id__ = "S30"


def rule_s44(*args, **kwargs):
    """DPIImport is promoted in pass 1 of dispatch.promote — see the S44
    branch.  This stub registers ``SyntaxKind.DPIImport`` under an active
    ``__rule_id__`` for the Bucket-1 checklist and the ``_ACTIVE_RULE_IDS``
    gate in dispatch.  The promotion logic lives inline in pass 1 because
    DPI imports, like extern module declarations and clocking blocks, need
    the enclosing module_stack context that is only available during the
    DFS traversal."""
    return


rule_s44.__rule_id__ = "S44"


def rule_s45(*args, **kwargs):
    """DPIExport is promoted in pass 1 of dispatch.promote — see the S45
    branch.  This stub registers ``SyntaxKind.DPIExport`` under an active
    ``__rule_id__`` for the Bucket-1 checklist and the ``_ACTIVE_RULE_IDS``
    gate in dispatch.  S45 is edge-only: a ``dpi_exports`` edge is emitted
    from the enclosing scope node to the target SV function node (resolved
    via name_index, or ``_unresolved.<name>`` when absent).  No new node is
    created — the export names an existing function and makes it C-visible;
    it has no independent identity in the knowledge graph."""
    return


rule_s45.__rule_id__ = "S45"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ExternModuleDecl, _s29_extern_module_decl),
    (pyslang.SyntaxKind.ProgramDeclaration, _s30_program_decl),
    (pyslang.SyntaxKind.DPIImport, rule_s44),
    (pyslang.SyntaxKind.DPIExport, rule_s45),
]
