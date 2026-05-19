"""S89 — ``ProgramHeader`` ownership-only marker.

``SyntaxKind.ProgramHeader`` is the header portion of a
``ProgramDeclaration`` — the ``program [lifetime] <name>
[#(parameter port list)] [(port list)] ;`` clause that precedes the
program body. pyslang reuses the single ``ModuleHeaderSyntax`` Python
class across the four header SyntaxKind variants (``ModuleHeader`` /
``InterfaceHeader`` / ``PackageHeader`` / ``ProgramHeader`` —
``CLAUDE.md`` lesson 1 shared class, discriminator on ``node.kind``).

Semantic content already lifted onto the parent ``ProgramDeclaration``
semantic node:

* ``role="program"`` / ``name`` / ``path`` come from S1's
  ``ModuleDeclarationSyntax`` branch under the ``ProgramDeclaration``
  kind discriminator (lifted into a dedicated S30 program promotion).
* Any parameters / ports that appear surface via the existing
  ``ParameterDeclaration`` (S1) / port-shape (S1 / S64 / S65 / S66)
  branches under the header's ``parameters`` / ``ports`` subtrees.

Per ``CLAUDE.md`` lesson 5 (header ownership marker), the header itself
has no independent identity worth promoting — adding a dispatch branch
would double-promote the program. We register an **ownership-only stub**
so the Bucket-1 checklist marks ``ProgramHeader`` as ``Sem ✅`` (owner
S89) without runtime behaviour. Mirrors S85 / S87 / S88.

Tests:

* S89 is registered in ``dispatch._ACTIVE_RULE_IDS``.
* The metadata stub registered for ``SyntaxKind.ProgramHeader`` pins
  ``__rule_id__ == 'S89'`` and there is exactly one such registration.
* ``SyntaxKind.ProgramHeader`` resolves through the composed
  ``RULE_TABLE`` (no duplicate-dispatch assertion fires when the rules
  package is imported, and the kind maps to the S89 stub).
* No node with ``role == 'program_header'`` is emitted into the graph
  from the live corpus — the stub is ownership-only.
* The existing ``role == 'program'`` count from
  ``corpus/extern_corpus.sv`` is unchanged (S89 must not double-promote
  the program that S1/S30 owns).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "extern_corpus.sv"


@pytest.fixture(scope="module")
def s89_bundle():
    """Lift + promote ``corpus/extern_corpus.sv`` (contains a ``program``)."""
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s89_in_active_rule_ids():
    """S89 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S89" in _ACTIVE_RULE_IDS


def test_s89_stub_owns_program_header():
    """The metadata stub registered for ``SyntaxKind.ProgramHeader`` must
    pin ``__rule_id__ == 'S89'`` and there must be exactly one
    registration for the kind."""
    from knowledge_graph.builders.sv.semantic.rules import structure
    matches = [
        fn for (kind, fn) in structure.RULES
        if kind == pyslang.SyntaxKind.ProgramHeader
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for ProgramHeader, got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S89"


def test_s89_dispatches_through_rule_table():
    """``SyntaxKind.ProgramHeader`` must resolve through the composed
    ``RULE_TABLE`` (i.e. no duplicate-dispatch assertion fires when the
    rules package is imported, and the kind maps to the S89 stub)."""
    from knowledge_graph.builders.sv.semantic.rules import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.ProgramHeader)
    assert fn is not None, (
        "ProgramHeader missing from RULE_TABLE — structure.RULES did "
        "not register the S89 stub"
    )
    assert getattr(fn, "__rule_id__", None) == "S89"


def test_s89_emits_no_program_header_role(s89_bundle):
    """S89 is ownership-only: no graph node must carry
    ``role == 'program_header'`` (the header's semantic content is
    already lifted onto the parent ``ProgramDeclaration`` node)."""
    rogue = [n for n in s89_bundle["nodes"]
             if n.get("semantic", {}).get("role") == "program_header"]
    assert rogue == [], (
        f"S89 must not emit program_header nodes, got {len(rogue)}: "
        f"{[n['semantic'] for n in rogue]}"
    )


def test_s89_does_not_change_program_count(s89_bundle):
    """``corpus/extern_corpus.sv`` contains 1 ``program ... endprogram``
    block (``ext_prog``). S89 must not double-promote it — the
    S1/S30-owned ``role == 'program'`` count stays at 1."""
    programs = [n for n in s89_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "program"]
    assert len(programs) == 1, (
        f"expected exactly 1 role=program node from extern_corpus.sv, "
        f"got {len(programs)}: "
        f"{[n['semantic'] for n in programs]}"
    )
