"""S87 — ``ModuleHeader`` ownership-only marker.

``SyntaxKind.ModuleHeader`` is the header portion of a
``ModuleDeclaration`` — the ``module [lifetime] <name>
[#(parameter port list)] [(port list)] ;`` clause that precedes the
module body. pyslang reuses the single ``ModuleHeaderSyntax`` Python
class across the four header SyntaxKind variants (``ModuleHeader`` /
``InterfaceHeader`` / ``PackageHeader`` / ``ProgramHeader`` —
``CLAUDE.md`` lesson 1 shared class, discriminator on ``node.kind``).

Semantic content already lifted onto the parent ``ModuleDeclaration``
semantic node:

* ``role="module"`` / ``name`` / ``path`` come from S1's
  ``ModuleDeclarationSyntax`` branch.
* ``parameters`` already surface via the existing ``ParameterDeclaration``
  (S1) branch under the header's ``parameters`` subtree.
* ``ports`` already surface via the existing ``ImplicitAnsiPort`` (S1) /
  ``ExplicitAnsiPort`` (S64) / ``ExplicitNonAnsiPort`` (S65) /
  ``ImplicitNonAnsiPort`` (S66) branches under the header's ``ports``
  subtree.

Per ``CLAUDE.md`` lesson 5 (header ownership marker), the header itself
has no independent identity worth promoting — adding a dispatch branch
would double-promote the module. We register an **ownership-only stub**
so the Bucket-1 checklist marks ``ModuleHeader`` as ``Sem ✅`` (owner
S87) without runtime behaviour. Mirrors S85.

Tests:

* S87 is registered in ``dispatch._ACTIVE_RULE_IDS``.
* The metadata stub registered for ``SyntaxKind.ModuleHeader`` pins
  ``__rule_id__ == 'S87'`` and there is exactly one such registration.
* ``SyntaxKind.ModuleHeader`` resolves through the composed
  ``RULE_TABLE`` (no duplicate-dispatch assertion fires when the rules
  package is imported, and the kind maps to the S87 stub).
* No node with ``role == 'module_header'`` is emitted into the graph
  from the live corpus — the stub is ownership-only.
* The existing ``role == 'module'`` count from ``corpus/fifo.sv`` is
  unchanged (S87 must not double-promote the module that S1 owns).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def s87_bundle():
    """Lift + promote ``corpus/fifo.sv`` (contains a ``module``)."""
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s87_in_active_rule_ids():
    """S87 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S87" in _ACTIVE_RULE_IDS


def test_s87_stub_owns_module_header():
    """The metadata stub registered for ``SyntaxKind.ModuleHeader`` must
    pin ``__rule_id__ == 'S87'`` and there must be exactly one
    registration for the kind."""
    from research.ast_experiment.src.semantic.rules import structure
    matches = [
        fn for (kind, fn) in structure.RULES
        if kind == pyslang.SyntaxKind.ModuleHeader
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for ModuleHeader, got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S87"


def test_s87_dispatches_through_rule_table():
    """``SyntaxKind.ModuleHeader`` must resolve through the composed
    ``RULE_TABLE`` (i.e. no duplicate-dispatch assertion fires when the
    rules package is imported, and the kind maps to the S87 stub)."""
    from research.ast_experiment.src.semantic.rules import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.ModuleHeader)
    assert fn is not None, (
        "ModuleHeader missing from RULE_TABLE — structure.RULES did "
        "not register the S87 stub"
    )
    assert getattr(fn, "__rule_id__", None) == "S87"


def test_s87_emits_no_module_header_role(s87_bundle):
    """S87 is ownership-only: no graph node must carry
    ``role == 'module_header'`` (the header's semantic content is
    already lifted onto the parent ``ModuleDeclaration`` node)."""
    rogue = [n for n in s87_bundle["nodes"]
             if n.get("semantic", {}).get("role") == "module_header"]
    assert rogue == [], (
        f"S87 must not emit module_header nodes, got {len(rogue)}: "
        f"{[n['semantic'] for n in rogue]}"
    )


def test_s87_does_not_change_module_count(s87_bundle):
    """``corpus/fifo.sv`` contains 12 ``module ... endmodule`` blocks.
    S87 must not double-promote them — the S1-owned ``role == 'module'``
    count stays at 12 (one per module declaration in the corpus file)."""
    modules = [n for n in s87_bundle["nodes"]
               if n.get("semantic", {}).get("role") == "module"]
    assert len(modules) == 12, (
        f"expected exactly 12 role=module nodes from fifo.sv, "
        f"got {len(modules)}: "
        f"{[n['semantic'] for n in modules]}"
    )
