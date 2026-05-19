"""S78: ``AssertionItemPortList`` ownership-only marker.

``AssertionItemPortList`` is the parenthesised wrapper containing one
or more ``AssertionItemPort`` entries inside a parameterised property /
sequence / let signature (``property p(logic sig, int n); ...`` — the
``(logic sig, int n)`` parses as an ``AssertionItemPortListSyntax``
holding the two ``AssertionItemPortSyntax`` children).

Per ``CLAUDE.md`` lesson 5 (wrapper-kind dedup), the wrapper carries no
independent identity beyond its children. We leave it as CONTAINER for
structural traversal and add an ownership-only stub so the Bucket-1
checklist marks ``AssertionItemPortList`` as ``Sem ✅`` (owned by S78)
without adding a dispatch branch. The child ``AssertionItemPort`` nodes
continue to promote via S77.

Tests:

* S78 is registered in ``dispatch._ACTIVE_RULE_IDS``
* The metadata stub is reachable in ``rules.assertions.RULES`` and pins
  ``__rule_id__ == "S78"`` on the ``AssertionItemPortList`` kind
* The wrapper itself produces no ``role=assertion_item_port_list`` node
* The S77 ``assertion_item_port`` promotion count is unchanged
  (eleven per the S77 baseline established at iter-095)
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
CORPUS_DIR = HERE / "corpus"
ASSERTS = CORPUS_DIR / "fifo_asserts.sv"


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
def asserts_graph():
    return _graph_for(ASSERTS)


def test_s78_in_active_rule_ids():
    """S78 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S78" in _ACTIVE_RULE_IDS


def test_s78_stub_owns_assertion_item_port_list():
    """The metadata stub registered for ``SyntaxKind.AssertionItemPortList``
    must pin ``__rule_id__ == 'S78'``."""
    from knowledge_graph.builders.sv.semantic.rules import assertions
    matches = [
        fn for (kind, fn) in assertions.RULES
        if kind == pyslang.SyntaxKind.AssertionItemPortList
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for AssertionItemPortList, "
        f"got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S78"


def test_no_assertion_item_port_list_node(asserts_graph):
    """The wrapper must NOT produce a ``role=assertion_item_port_list``
    node — only its ``AssertionItemPort`` children promote (via S77)."""
    wrappers = [n for n in asserts_graph["nodes"]
                if n.get("semantic", {}).get("role")
                == "assertion_item_port_list"]
    assert wrappers == [], (
        f"AssertionItemPortList wrapper unexpectedly promoted to a node: "
        f"{wrappers}"
    )


def test_s77_assertion_item_port_count_unchanged(asserts_graph):
    """Eleven ``role=assertion_item_port`` nodes total per the S77
    baseline (iter-095). S78 must not perturb this count."""
    ports = [n for n in asserts_graph["nodes"]
             if n.get("semantic", {}).get("role") == "assertion_item_port"]
    assert len(ports) == 11, (
        f"assertion_item_port count drifted: {len(ports)}; "
        f"paths={[p['semantic'].get('path') for p in ports]}"
    )
