"""S29 — Extern module / interface / program declarations.

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

Future S-rules in this module:

* ``ProgramDeclaration`` (S30 — full program body, not the extern header).
* ``AnonymousProgram`` is also planned here.

The metadata stub below pins ``__rule_id__="S29"`` against
``pyslang.SyntaxKind.ExternModuleDecl`` so the registry-derived Bucket-1
checklist counts the kind as PROMOTE_NOW.
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


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ExternModuleDecl, _s29_extern_module_decl),
]
