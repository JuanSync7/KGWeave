"""S76: ``DefaultFunctionPort`` ownership-only marker.

``DefaultFunctionPortSyntax`` represents the bare ``default`` keyword that
pyslang's grammar allows in a ``FunctionPortListSyntax`` (e.g. ``(default)``
or ``(input int a, default)``). The construct is reserved in pyslang's
SyntaxKind enum but the parser always raises ``DefaultArgNotAllowed`` —
no clean SystemVerilog program contains a ``DefaultFunctionPort``.

Per ``CLAUDE.md`` lesson 4 / lesson 5 (ownership-only stub for a kind with
no clean-SV instantiation), S76 is registered as an ownership marker only:

* metadata entry ``(SyntaxKind.DefaultFunctionPort, _s76_stub)`` with
  ``__rule_id__='S76'`` appended to ``rules/procedural.RULES``
* ``"S76"`` added to ``dispatch._ACTIVE_RULE_IDS`` so the bucket1 checklist
  regenerator attributes the kind to S76
* NO dispatch branch — the kind never appears in any KGWeave corpus (all
  corpus files round-trip with zero diagnostics, and pyslang flags every
  ``DefaultFunctionPort`` instance with ``DefaultArgNotAllowed``).

Tests:

* S76 is registered in ``dispatch._ACTIVE_RULE_IDS``
* The metadata stub is reachable in ``rules.procedural.RULES`` and pins
  ``__rule_id__ == 'S76'`` on the ``DefaultFunctionPort`` kind
* The S74 ``function_port`` promotion count is unchanged (six total across
  fifo.sv + extern_corpus.sv per the S74 baseline at iter-092)
* No ``DefaultFunctionPort`` syntax node appears in any corpus file (the
  honest-coverage assertion: if a future corpus addition ever produces one,
  this test fails and the stub must be upgraded to a real dispatch branch)
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
CORPUS_DIR = HERE / "corpus"
FIFO = CORPUS_DIR / "fifo.sv"
EXTERN = CORPUS_DIR / "extern_corpus.sv"


def _graph_for(path: Path):
    text = path.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


@pytest.fixture(scope="module")
def fifo_graph():
    return _graph_for(FIFO)


@pytest.fixture(scope="module")
def extern_graph():
    return _graph_for(EXTERN)


def test_s76_in_active_rule_ids():
    """S76 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S76" in _ACTIVE_RULE_IDS


def test_s76_stub_owns_default_function_port():
    """The metadata stub registered for ``SyntaxKind.DefaultFunctionPort``
    must pin ``__rule_id__ == 'S76'``."""
    from knowledge_graph.builders.sv.semantic.rules import procedural
    matches = [
        fn for (kind, fn) in procedural.RULES
        if kind == pyslang.SyntaxKind.DefaultFunctionPort
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for DefaultFunctionPort, "
        f"got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S76"


def test_s74_function_port_count_unchanged(fifo_graph, extern_graph):
    """Seven ``role=function_port`` nodes total — two from fifo (next_ptr.p,
    sv_compute.x) and five from extern_corpus (helper_add.a, helper_add.b,
    helper_log.msg, helper_pulse.sig, helper_forkjoin.sig — the last
    contributed by the S80 forkjoin task). S76 must not perturb this count."""
    fifo_ports = [n for n in fifo_graph["nodes"]
                  if n.get("semantic", {}).get("role") == "function_port"]
    extern_ports = [n for n in extern_graph["nodes"]
                    if n.get("semantic", {}).get("role") == "function_port"]
    assert len(fifo_ports) == 2, (
        f"fifo function_port count drifted: {len(fifo_ports)}; "
        f"names={[p['semantic'].get('name') for p in fifo_ports]}"
    )
    assert len(extern_ports) == 5, (
        f"extern function_port count drifted: {len(extern_ports)}; "
        f"names={[p['semantic'].get('name') for p in extern_ports]}"
    )


def test_no_default_function_port_in_corpus():
    """Honest-coverage assertion: no corpus file may contain a
    ``DefaultFunctionPort`` syntax node. pyslang flags every instance of
    this kind with ``DefaultArgNotAllowed``, and the corpus is required
    to round-trip with zero diagnostics — so the count must be zero.

    If a future corpus addition ever triggers this assertion, the stub
    must be upgraded to a real dispatch branch (with the function_stack
    parent-resolution scheme from S74) and this test rewritten.
    """
    target = pyslang.SyntaxKind.DefaultFunctionPort
    for sv in sorted(CORPUS_DIR.glob("*.sv")):
        tree = pyslang.SyntaxTree.fromText(sv.read_text())
        hits: list = []

        def _visit(n, _hits=hits):
            try:
                if n.kind == target:
                    _hits.append(n)
            except Exception:
                return
            try:
                for c in n:
                    if c is not None and hasattr(c, "kind"):
                        _visit(c)
            except Exception:
                return

        _visit(tree.root)
        assert hits == [], (
            f"{sv.name}: unexpected DefaultFunctionPort instances "
            f"({len(hits)}). The S76 stub assumes this kind is "
            f"unreachable in clean SV — upgrade to a dispatch branch."
        )
