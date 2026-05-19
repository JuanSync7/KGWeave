"""S80: ``ExternInterfaceMethod`` wrapper ownership + ``forkjoin`` attribute lift.

``ExternInterfaceMethodSyntax`` is the interface-scope wrapper around an
``extern function|task`` declaration. The inner ``FunctionPrototypeSyntax``
is already promoted by S56 (see ``test_extern.py`` S56 block). Per lesson
5 (wrapper-kind dedup), registering the wrapper as its own queryable node
would double-promote against the S56 inner — instead S80:

* Owns the ``ExternInterfaceMethod`` SyntaxKind for the Bucket-1 checklist
  via an ownership-only stub (``rule_s80.__rule_id__ == "S80"``).
* Lifts the single wrapper-only attribute the inner FunctionPrototype
  cannot see — the optional ``forkjoin`` keyword (LRM 25.10, ``extern
  forkjoin task``) — onto the S56 node's ``attributes["forkjoin"]``.

The wrapper itself stays CONTAINER. Queryable identity remains on the
inner FunctionPrototype.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
EXT = HERE / "corpus" / "extern_corpus.sv"


@pytest.fixture(scope="module")
def ext_graph():
    text = EXT.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _by_role(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role]


def test_s80_in_active_rule_ids():
    """S80 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S80" in _ACTIVE_RULE_IDS


def test_s80_stub_owns_extern_interface_method():
    """The metadata stub registered for ``SyntaxKind.ExternInterfaceMethod``
    must pin ``__rule_id__ == 'S80'``."""
    from research.ast_experiment.src.semantic.rules import extern
    matches = [
        fn for (kind, fn) in extern.RULES
        if kind == pyslang.SyntaxKind.ExternInterfaceMethod
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for ExternInterfaceMethod, "
        f"got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S80"


def test_no_extern_interface_method_node(ext_graph):
    """The wrapper must NOT produce a ``role=extern_interface_method`` node
    (lesson 5 — only the innermost queryable kind, S56's
    function_prototype, promotes)."""
    wrappers = [n for n in ext_graph["nodes"]
                if n.get("semantic", {}).get("role")
                == "extern_interface_method"]
    assert wrappers == [], (
        f"ExternInterfaceMethod wrapper unexpectedly promoted to a node: "
        f"{wrappers}"
    )


def test_s80_forkjoin_attribute_default_false(ext_graph):
    """The three plain ``extern function|task`` prototypes (no ``forkjoin``
    keyword) must carry ``forkjoin=False`` on the S56 node."""
    protos = {p["semantic"]["name"]: p
              for p in _by_role(ext_graph, "function_prototype")}
    assert protos["helper_add"]["semantic"]["attributes"]["forkjoin"] is False
    assert protos["helper_log"]["semantic"]["attributes"]["forkjoin"] is False
    assert protos["helper_pulse"]["semantic"]["attributes"]["forkjoin"] is False


def test_s80_forkjoin_attribute_lifted(ext_graph):
    """The ``extern forkjoin task helper_forkjoin(...);`` declaration must
    surface as an S56 function_prototype node with ``forkjoin=True`` lifted
    from the S80 wrapper."""
    protos = {p["semantic"]["name"]: p
              for p in _by_role(ext_graph, "function_prototype")}
    assert "helper_forkjoin" in protos, (
        f"helper_forkjoin missing from prototype set: {sorted(protos)}"
    )
    fj = protos["helper_forkjoin"]["semantic"]["attributes"]
    assert fj["forkjoin"] is True
    # Sanity-check the rest of the S56 attribute payload on the forkjoin
    # task — the wrapper context must not perturb the inner extraction.
    assert fj["kind"] == "task"
    assert fj["return_type"] is None
    assert fj["is_extern"] is True
    assert fj["port_count"] == 1


def test_s80_does_not_perturb_s56_count(ext_graph):
    """The corpus adds one new extern method (``helper_forkjoin``); the
    S56 function_prototype roster grows to 4 names — no double-promotion
    and no skipped prototypes."""
    protos = _by_role(ext_graph, "function_prototype")
    names = sorted(p["semantic"]["name"] for p in protos)
    assert names == [
        "helper_add", "helper_forkjoin", "helper_log", "helper_pulse",
    ], names
