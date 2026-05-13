"""S16: concurrent-assertion-statement promotion.

The corpus's ``fifo_asserts.sv`` carries four concurrent assertions inside
``module fifo_asserts``:

* ``a_no_push_when_full: assert property (...)`` — labeled
* ``a_push_implies_seq: assume property (...)`` — labeled
* ``c_push_event: cover property (...)`` — labeled
* ``cover property (...)`` — UNlabeled (synthetic ``cover_<n>`` fallback)

Plus a free-form inline test fixture exercising the remaining three kinds
(``restrict property``, ``expect`` in a procedural block, and
``cover sequence``) so every registered SyntaxKind is hit.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
BIND = HERE / "fifo_asserts.sv"


@pytest.fixture(scope="module")
def bind_graph():
    text = BIND.read_text()
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


def _assertions(graph):
    return _by_role(graph, "assertion")


def test_s16_assert_property_promoted(bind_graph):
    """The labeled ``a_no_push_when_full`` assert is promoted with the
    correct kind attribute and hierarchical path."""
    matches = [a for a in _assertions(bind_graph)
               if a["semantic"]["name"] == "a_no_push_when_full"]
    assert len(matches) == 1, f"expected one assert node, got {len(matches)}"
    a = matches[0]
    assert a["semantic"]["path"] == "fifo_asserts.a_no_push_when_full"
    assert a["semantic"]["attributes"]["kind"] == "assert"


def test_s16_assume_property_promoted(bind_graph):
    """The labeled ``a_push_implies_seq`` assume is promoted with kind=assume."""
    matches = [a for a in _assertions(bind_graph)
               if a["semantic"]["name"] == "a_push_implies_seq"]
    assert len(matches) == 1
    a = matches[0]
    assert a["semantic"]["path"] == "fifo_asserts.a_push_implies_seq"
    assert a["semantic"]["attributes"]["kind"] == "assume"


def test_s16_cover_property_labeled_promoted(bind_graph):
    """The labeled ``c_push_event`` cover is promoted with kind=cover."""
    matches = [a for a in _assertions(bind_graph)
               if a["semantic"]["name"] == "c_push_event"]
    assert len(matches) == 1
    a = matches[0]
    assert a["semantic"]["path"] == "fifo_asserts.c_push_event"
    assert a["semantic"]["attributes"]["kind"] == "cover"


def test_s16_unlabeled_cover_gets_synthetic_label(bind_graph):
    """The unlabeled ``cover property (...)`` gets a synthetic ``cover_<n>``
    label and is registered in the name index under
    ``fifo_asserts.cover_<n>``."""
    covers = [a for a in _assertions(bind_graph)
              if a["semantic"]["attributes"]["kind"] == "cover"
              and a["semantic"]["name"] != "c_push_event"]
    assert len(covers) == 1, f"expected one synthetic-label cover, got {len(covers)}"
    a = covers[0]
    assert a["semantic"]["name"].startswith("cover_"), a["semantic"]["name"]
    assert a["semantic"]["path"] == f"fifo_asserts.{a['semantic']['name']}"
    idx = bind_graph.get("semantic_name_index", {})
    assert a["semantic"]["path"] in idx


def test_s16_has_assertion_edges(bind_graph):
    """Each promoted assertion has exactly one ``has_assertion`` edge from
    the parent module ``fifo_asserts``."""
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules if m["semantic"]["name"] == "fifo_asserts"), None)
    assert parent is not None
    assertions = _assertions(bind_graph)
    assert len(assertions) == 4, (
        f"expected 4 assertions from fifo_asserts.sv, got {len(assertions)}"
    )
    for a in assertions:
        edges = [e for e in bind_graph["edges"]
                 if e["type"] == "has_assertion"
                 and e["src"] == parent["id"]
                 and e["dst"] == a["id"]]
        assert len(edges) == 1, (
            f"expected one has_assertion edge for {a['semantic']['path']}, got {len(edges)}"
        )


def test_s16_name_index_registers_labeled_paths(bind_graph):
    """All three labeled assertions are reachable via the semantic name index
    under their fully-qualified ``<module>.<label>`` paths."""
    idx = bind_graph.get("semantic_name_index", {})
    for path in [
        "fifo_asserts.a_no_push_when_full",
        "fifo_asserts.a_push_implies_seq",
        "fifo_asserts.c_push_event",
    ]:
        assert path in idx, f"missing {path} in semantic_name_index"


# ---------------------------------------------------------------------------
# Inline corpus — restrict / expect / cover_sequence and the parent-resolution
# check for assertions inside a procedural block.
# ---------------------------------------------------------------------------


_INLINE = """
module m_inline;
  logic clk, push, full;
  // restrict property at module top-level (ConcurrentAssertionMember wrap).
  // Pyslang does not accept ``label:`` on restrict — synthetic label only.
  restrict property (@(posedge clk) push |-> !full);
  // cover sequence at module top-level.
  cs_push: cover sequence (@(posedge clk) push);
  // assertion nested inside a procedural block — parent must still be m_inline,
  // not the always_ff block.
  always_ff @(posedge clk) begin
    a_nested: assert property (@(posedge clk) push |-> !full);
  end
  // expect in a procedural block (this is where ExpectPropertyStatement parses).
  initial begin
    expect (@(posedge clk) push);
  end
endmodule
"""


@pytest.fixture(scope="module")
def inline_graph():
    tree = pyslang.SyntaxTree.fromText(_INLINE)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s16_restrict_property_promoted(inline_graph):
    """``restrict property`` becomes role=assertion with kind=restrict."""
    matches = [a for a in _assertions(inline_graph)
               if a["semantic"]["attributes"]["kind"] == "restrict"]
    assert len(matches) == 1
    a = matches[0]
    # No label accepted by pyslang on restrict — synthetic ``restrict_<n>``.
    assert a["semantic"]["name"].startswith("restrict_"), a["semantic"]["name"]
    assert a["semantic"]["path"].startswith("m_inline."), a["semantic"]["path"]


def test_s16_cover_sequence_promoted(inline_graph):
    """``cover sequence`` becomes role=assertion with kind=cover_sequence."""
    matches = [a for a in _assertions(inline_graph)
               if a["semantic"]["attributes"]["kind"] == "cover_sequence"]
    assert len(matches) == 1
    assert matches[0]["semantic"]["name"] == "cs_push"


def test_s16_expect_promoted_inside_procedural_block(inline_graph):
    """``expect (...)`` inside an ``initial`` block becomes role=assertion
    with kind=expect; its parent is the module, not the initial block."""
    matches = [a for a in _assertions(inline_graph)
               if a["semantic"]["attributes"]["kind"] == "expect"]
    assert len(matches) == 1
    a = matches[0]
    # No label in the corpus — synthetic ``expect_<n>``.
    assert a["semantic"]["name"].startswith("expect_"), a["semantic"]["name"]
    assert a["semantic"]["path"].startswith("m_inline."), a["semantic"]["path"]


def test_s16_assertion_in_procedural_block_parents_to_module(inline_graph):
    """``a_nested`` lives inside ``always_ff`` but its has_assertion edge
    originates at ``m_inline``, not at the always_ff block."""
    nested = [a for a in _assertions(inline_graph)
              if a["semantic"]["name"] == "a_nested"]
    assert len(nested) == 1
    a = nested[0]
    modules = _by_role(inline_graph, "module")
    parent = next(m for m in modules if m["semantic"]["name"] == "m_inline")
    edges = [e for e in inline_graph["edges"]
             if e["type"] == "has_assertion"
             and e["src"] == parent["id"]
             and e["dst"] == a["id"]]
    assert len(edges) == 1
    assert a["semantic"]["path"] == "m_inline.a_nested"
    assert a["semantic"]["attributes"]["kind"] == "assert"


def test_s16_inline_module_assertion_count(inline_graph):
    """The inline corpus contributes exactly four assertions."""
    assert len(_assertions(inline_graph)) == 4
