"""S79: ``CheckerInstanceStatement`` ownership-only marker.

``CheckerInstanceStatement`` is the procedural-scope wrapper around a
``CheckerInstantiation`` — pyslang parses ``c_mutex u_proc (...)`` inside
an ``initial`` / ``always_*`` block as a
``CheckerInstanceStatementSyntax`` whose ``.instance`` attribute is the
inner ``CheckerInstantiationSyntax``. The module-scope form parses as a
``HierarchyInstantiation`` (reclassified by ``rule_s6``) and the
procedural-scope inner ``CheckerInstantiation`` is already promoted by
S28's pass-1 branch.

Per ``CLAUDE.md`` lesson 5 (wrapper-kind dedup), the wrapper carries no
independent identity beyond the inner instance — registering both
wrapper and inner kinds would double-promote. We therefore leave the
wrapper as CONTAINER for structural traversal and add an ownership-only
stub so the Bucket-1 checklist marks ``CheckerInstanceStatement`` as
``Sem ✅`` (owned by S79). The child ``CheckerInstantiation`` continues
to promote via S28. Pattern mirrors S70 / S71 / S75 / S78.

Tests:

* S79 is registered in ``dispatch._ACTIVE_RULE_IDS``
* The metadata stub is reachable in ``rules.checkers.RULES`` and pins
  ``__rule_id__ == "S79"`` on the ``CheckerInstanceStatement`` kind
* The wrapper itself produces no ``role=checker_instance_statement``
  node (it stays CONTAINER)
* The procedural-scope instance promotes to exactly one
  ``role=checker_instance`` node (via S28) — no double-promotion
* The combined corpus contains exactly two ``checker_instance`` nodes
  (one module-scope ``u_mutex``, one procedural-scope ``u_proc``)
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
CORPUS_DIR = HERE / "corpus"
CHECKER = CORPUS_DIR / "checker_corpus.sv"


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
def checker_graph():
    return _graph_for(CHECKER)


def test_s79_in_active_rule_ids():
    """S79 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S79" in _ACTIVE_RULE_IDS


def test_s79_stub_owns_checker_instance_statement():
    """The metadata stub registered for ``SyntaxKind.CheckerInstanceStatement``
    must pin ``__rule_id__ == 'S79'``."""
    from knowledge_graph.builders.sv.semantic.rules import checkers
    matches = [
        fn for (kind, fn) in checkers.RULES
        if kind == pyslang.SyntaxKind.CheckerInstanceStatement
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for CheckerInstanceStatement, "
        f"got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S79"


def test_no_checker_instance_statement_node(checker_graph):
    """The wrapper must NOT produce a ``role=checker_instance_statement``
    node — only its inner ``CheckerInstantiation`` promotes (via S28)."""
    wrappers = [n for n in checker_graph["nodes"]
                if n.get("semantic", {}).get("role")
                == "checker_instance_statement"]
    assert wrappers == [], (
        f"CheckerInstanceStatement wrapper unexpectedly promoted to a node: "
        f"{wrappers}"
    )


def test_procedural_scope_checker_instance_promotes_once(checker_graph):
    """The procedural-scope checker instance ``u_proc`` (inside the
    ``initial`` block of ``checker_corpus_top``) must promote to exactly
    one ``role=checker_instance`` node — no double-promotion via the
    wrapper, and the inner ``CheckerInstantiation`` must still fire."""
    u_proc = [n for n in checker_graph["nodes"]
              if n.get("semantic", {}).get("role") == "checker_instance"
              and n["semantic"].get("name") == "u_proc"]
    assert len(u_proc) == 1, (
        f"u_proc must promote exactly once, got {len(u_proc)}: "
        f"{[n['semantic'] for n in u_proc]}"
    )
    sem = u_proc[0]["semantic"]
    assert sem.get("path") == "checker_corpus_top.u_proc"
    assert sem.get("attributes", {}).get("checker_name") == "c_mutex"


def test_total_checker_instance_count(checker_graph):
    """Exactly two ``checker_instance`` nodes exist in the corpus: the
    module-scope ``u_mutex`` (via ``rule_s6`` reclassification) and the
    procedural-scope ``u_proc`` (via S28 + S79 wrapper)."""
    ci = [n for n in checker_graph["nodes"]
          if n.get("semantic", {}).get("role") == "checker_instance"]
    names = sorted(n["semantic"].get("name") for n in ci)
    assert names == ["u_mutex", "u_proc"], (
        f"checker_instance names drifted: {names}"
    )
