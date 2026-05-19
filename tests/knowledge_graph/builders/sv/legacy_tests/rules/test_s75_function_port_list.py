"""S75: ``FunctionPortList`` ownership-only marker.

``FunctionPortList`` is the parenthesised wrapper containing one or more
``FunctionPort`` entries inside a function / task / method signature
(``function int add(input int a, output int b);`` — the
``(input int a, output int b)`` parses as a ``FunctionPortListSyntax``
holding two ``FunctionPortSyntax`` children).

Per ``CLAUDE.md`` lesson 5 (wrapper-kind dedup), the wrapper carries no
independent identity beyond its children. We leave it as CONTAINER for
structural traversal and add an ownership-only stub so the Bucket-1
checklist marks ``FunctionPortList`` as ``Sem ✅`` (owned by S75) without
adding a dispatch branch. The child ``FunctionPort`` nodes continue to
promote via S74.

Tests:

* S75 is registered in ``dispatch._ACTIVE_RULE_IDS``
* The metadata stub is reachable in ``rules.procedural.RULES`` and pins
  ``__rule_id__ == "S75"`` on the ``FunctionPortList`` kind
* The wrapper itself produces no ``role=function_port_list`` node
* The S74 ``function_port`` promotion count is unchanged (six per the
  S74 baseline established at iter-092)
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
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


@pytest.fixture(scope="module")
def fifo_graph():
    return _graph_for(FIFO)


@pytest.fixture(scope="module")
def extern_graph():
    return _graph_for(EXTERN)


def test_s75_in_active_rule_ids():
    """S75 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S75" in _ACTIVE_RULE_IDS


def test_s75_stub_owns_function_port_list():
    """The metadata stub registered for ``SyntaxKind.FunctionPortList``
    must pin ``__rule_id__ == 'S75'``."""
    from research.ast_experiment.src.semantic.rules import procedural
    matches = [
        fn for (kind, fn) in procedural.RULES
        if kind == pyslang.SyntaxKind.FunctionPortList
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for FunctionPortList, "
        f"got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S75"


def test_no_function_port_list_node(fifo_graph, extern_graph):
    """The wrapper must NOT produce a ``role=function_port_list`` node —
    only its ``FunctionPort`` children promote (via S74)."""
    for graph in (fifo_graph, extern_graph):
        wrappers = [n for n in graph["nodes"]
                    if n.get("semantic", {}).get("role")
                    == "function_port_list"]
        assert wrappers == [], (
            f"FunctionPortList wrapper unexpectedly promoted to a node: "
            f"{wrappers}"
        )


def test_s74_function_port_count_unchanged(fifo_graph, extern_graph):
    """Seven ``role=function_port`` nodes total — two from fifo (next_ptr.p,
    sv_compute.x) and five from extern_corpus (helper_add.a, helper_add.b,
    helper_log.msg, helper_pulse.sig, helper_forkjoin.sig — the last
    contributed by the S80 forkjoin task added to extend wrapper coverage).
    S75 must not perturb this count."""
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
