"""S85 — ``InterfaceHeader`` ownership-only marker.

``SyntaxKind.InterfaceHeader`` is the header portion of an
``InterfaceDeclaration`` — the ``interface [lifetime] <name>
[#(parameter port list)] [(port list)] ;`` clause that precedes the
interface body. pyslang reuses the single ``ModuleHeaderSyntax`` Python
class across the four header SyntaxKind variants (``ModuleHeader`` /
``InterfaceHeader`` / ``PackageHeader`` / ``ProgramHeader`` —
``CLAUDE.md`` lesson 1 shared class, discriminator on ``node.kind``).

Semantic content already lifted onto the parent ``InterfaceDeclaration``
semantic node:

* ``role="interface"`` / ``name`` / ``path`` come from S1's
  ``ModuleDeclarationSyntax`` branch (discriminated on the
  ``InterfaceDeclaration`` ``SyntaxKind`` value).
* ``parameters`` already surface via the existing ``ParameterDeclaration``
  (S1) branch under the header's ``parameters`` subtree.
* ``ports`` already surface via the existing ``ImplicitAnsiPort`` (S1) /
  ``ExplicitAnsiPort`` (S64) / ``ExplicitNonAnsiPort`` (S65) /
  ``ImplicitNonAnsiPort`` (S66) branches under the header's ``ports``
  subtree.

Per ``CLAUDE.md`` lesson 5 (header ownership marker), the header itself
has no independent identity worth promoting — adding a dispatch branch
would double-promote the interface. We register an **ownership-only
stub** so the Bucket-1 checklist marks ``InterfaceHeader`` as
``Sem ✅`` (owner S85) without runtime behaviour. Mirrors S82 / S83.

Tests:

* S85 is registered in ``dispatch._ACTIVE_RULE_IDS``.
* The metadata stub registered for ``SyntaxKind.InterfaceHeader`` pins
  ``__rule_id__ == 'S85'`` and there is exactly one such registration.
* ``SyntaxKind.InterfaceHeader`` resolves through the composed
  ``RULE_TABLE`` (no duplicate-dispatch assertion fires when the rules
  package is imported, and the kind maps to the S85 stub).
* No node with ``role == 'interface_header'`` is emitted into the
  graph from the live corpus — the stub is ownership-only.
* The existing ``role == 'interface'`` count from ``corpus/fifo_if.sv``
  is unchanged (S85 must not double-promote the interface that S1 owns).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "fifo_if.sv"


@pytest.fixture(scope="module")
def s85_bundle():
    """Lift + promote ``corpus/fifo_if.sv`` (contains an ``interface``)."""
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s85_in_active_rule_ids():
    """S85 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S85" in _ACTIVE_RULE_IDS


def test_s85_stub_owns_interface_header():
    """The metadata stub registered for ``SyntaxKind.InterfaceHeader`` must
    pin ``__rule_id__ == 'S85'`` and there must be exactly one
    registration for the kind."""
    from knowledge_graph.builders.sv.semantic.rules import structure
    matches = [
        fn for (kind, fn) in structure.RULES
        if kind == pyslang.SyntaxKind.InterfaceHeader
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for InterfaceHeader, got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S85"


def test_s85_dispatches_through_rule_table():
    """``SyntaxKind.InterfaceHeader`` must resolve through the composed
    ``RULE_TABLE`` (i.e. no duplicate-dispatch assertion fires when the
    rules package is imported, and the kind maps to the S85 stub)."""
    from knowledge_graph.builders.sv.semantic.rules import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.InterfaceHeader)
    assert fn is not None, (
        "InterfaceHeader missing from RULE_TABLE — structure.RULES did "
        "not register the S85 stub"
    )
    assert getattr(fn, "__rule_id__", None) == "S85"


def test_s85_emits_no_interface_header_role(s85_bundle):
    """S85 is ownership-only: no graph node must carry
    ``role == 'interface_header'`` (the header's semantic content is
    already lifted onto the parent ``InterfaceDeclaration`` node)."""
    rogue = [n for n in s85_bundle["nodes"]
             if n.get("semantic", {}).get("role") == "interface_header"]
    assert rogue == [], (
        f"S85 must not emit interface_header nodes, got {len(rogue)}: "
        f"{[n['semantic'] for n in rogue]}"
    )


def test_s85_does_not_change_interface_count(s85_bundle):
    """``corpus/fifo_if.sv`` contains a single ``interface ... endinterface``
    block. S85 must not double-promote it — the S1-owned
    ``role == 'interface'`` count stays at 1."""
    interfaces = [n for n in s85_bundle["nodes"]
                  if n.get("semantic", {}).get("role") == "interface"]
    assert len(interfaces) == 1, (
        f"expected exactly 1 role=interface node from fifo_if.sv, "
        f"got {len(interfaces)}: "
        f"{[n['semantic'] for n in interfaces]}"
    )
