"""S88 — ``PackageHeader`` ownership-only marker.

``SyntaxKind.PackageHeader`` is the header portion of a
``PackageDeclaration`` — the ``package [lifetime] <name> ;`` clause that
precedes the package body. pyslang reuses the single
``ModuleHeaderSyntax`` Python class across the four header SyntaxKind
variants (``ModuleHeader`` / ``InterfaceHeader`` / ``PackageHeader`` /
``ProgramHeader`` — ``CLAUDE.md`` lesson 1 shared class, discriminator
on ``node.kind``).

Semantic content already lifted onto the parent ``PackageDeclaration``
semantic node:

* ``role="package"`` / ``name`` / ``path`` come from S1's
  ``ModuleDeclarationSyntax`` branch under the ``PackageDeclaration``
  kind discriminator.
* Any parameters that appear surface via the existing
  ``ParameterDeclaration`` (S1) branch.

Per ``CLAUDE.md`` lesson 5 (header ownership marker), the header itself
has no independent identity worth promoting — adding a dispatch branch
would double-promote the package. We register an **ownership-only stub**
so the Bucket-1 checklist marks ``PackageHeader`` as ``Sem ✅`` (owner
S88) without runtime behaviour. Mirrors S85 / S87.

Tests:

* S88 is registered in ``dispatch._ACTIVE_RULE_IDS``.
* The metadata stub registered for ``SyntaxKind.PackageHeader`` pins
  ``__rule_id__ == 'S88'`` and there is exactly one such registration.
* ``SyntaxKind.PackageHeader`` resolves through the composed
  ``RULE_TABLE`` (no duplicate-dispatch assertion fires when the rules
  package is imported, and the kind maps to the S88 stub).
* No node with ``role == 'package_header'`` is emitted into the graph
  from the live corpus — the stub is ownership-only.
* The existing ``role == 'package'`` count from ``corpus/fifo_pkg.sv``
  is unchanged (S88 must not double-promote the package that S1 owns).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "fifo_pkg.sv"


@pytest.fixture(scope="module")
def s88_bundle():
    """Lift + promote ``corpus/fifo_pkg.sv`` (contains a ``package``)."""
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s88_in_active_rule_ids():
    """S88 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S88" in _ACTIVE_RULE_IDS


def test_s88_stub_owns_package_header():
    """The metadata stub registered for ``SyntaxKind.PackageHeader`` must
    pin ``__rule_id__ == 'S88'`` and there must be exactly one
    registration for the kind."""
    from knowledge_graph.builders.sv.semantic.rules import structure
    matches = [
        fn for (kind, fn) in structure.RULES
        if kind == pyslang.SyntaxKind.PackageHeader
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for PackageHeader, got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S88"


def test_s88_dispatches_through_rule_table():
    """``SyntaxKind.PackageHeader`` must resolve through the composed
    ``RULE_TABLE`` (i.e. no duplicate-dispatch assertion fires when the
    rules package is imported, and the kind maps to the S88 stub)."""
    from knowledge_graph.builders.sv.semantic.rules import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.PackageHeader)
    assert fn is not None, (
        "PackageHeader missing from RULE_TABLE — structure.RULES did "
        "not register the S88 stub"
    )
    assert getattr(fn, "__rule_id__", None) == "S88"


def test_s88_emits_no_package_header_role(s88_bundle):
    """S88 is ownership-only: no graph node must carry
    ``role == 'package_header'`` (the header's semantic content is
    already lifted onto the parent ``PackageDeclaration`` node)."""
    rogue = [n for n in s88_bundle["nodes"]
             if n.get("semantic", {}).get("role") == "package_header"]
    assert rogue == [], (
        f"S88 must not emit package_header nodes, got {len(rogue)}: "
        f"{[n['semantic'] for n in rogue]}"
    )


def test_s88_does_not_change_package_count(s88_bundle):
    """``corpus/fifo_pkg.sv`` contains 1 ``package ... endpackage`` block.
    S88 must not double-promote it — the S1-owned ``role == 'package'``
    count stays at 1."""
    packages = [n for n in s88_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "package"]
    assert len(packages) == 1, (
        f"expected exactly 1 role=package node from fifo_pkg.sv, "
        f"got {len(packages)}: "
        f"{[n['semantic'] for n in packages]}"
    )
