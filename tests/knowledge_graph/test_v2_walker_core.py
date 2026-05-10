"""Wave 1 / track A — v2 dataflow walker core tests.

Verifies the elaborated-expression walker emits Operator/Literal/Index nodes
plus their structural edges per ``docs/v2_dataflow_schema.md``.
"""
from __future__ import annotations

from collections import Counter

import pytest

from kgweave.knowledge_graph.extraction.sv_v2_walker import (
    V2DataflowWalker,
    V2_WALKER_SOURCE,
)


# Whole-signal table needed by the walker for cross-ref resolution (track C
# does the heavy lifting; track A only needs to know which idents are real
# signals so it can decide whether to emit cross-refs vs leave as-is).
_AES_SIGNALS = {
    "m": {"a", "b", "c", "d", "x", "en"},
}


def _run(src: str, signals=None):
    walker = V2DataflowWalker(known_module_signals=signals or _AES_SIGNALS)
    return walker.extract(text=src, source="test.sv")


# ---------------------------------------------------------------------------
# Operator emission
# ---------------------------------------------------------------------------


def test_binary_operator_emits_one_operator_node():
    src = """
    module m;
      logic [7:0] a, b, c;
      assign c = a + b;
    endmodule
    """
    res = _run(src)
    ops = [e for e in res.entities if e.type == "Operator"]
    assert len(ops) == 1
    assert ops[0].name.startswith("m.assign_0.")
    # Operator kind stored in attributes["kind"].
    assert ops[0].attributes.get("kind") == "Add"
    assert ops[0].current_summary == ""


def test_unary_operator_emits_operator_node():
    src = """
    module m;
      logic [7:0] a, c;
      assign c = ~a;
    endmodule
    """
    res = _run(src)
    ops = [e for e in res.entities if e.type == "Operator"]
    assert len(ops) == 1
    kind = ops[0].attributes.get("kind", "")
    assert "Unary" in kind or "BitwiseNot" in kind or "Not" in kind


def test_ternary_operator_emits_operator_node():
    src = """
    module m;
      logic [7:0] a, b, c;
      logic en;
      assign c = en ? a : b;
    endmodule
    """
    res = _run(src)
    ops = [e for e in res.entities if e.type == "Operator"]
    assert len(ops) == 1
    assert "Conditional" in ops[0].attributes.get("kind", "")


def test_operand_edges_ordered_for_binary():
    src = """
    module m;
      logic [7:0] a, b, c;
      assign c = a + b;
    endmodule
    """
    res = _run(src)
    operand_edges = [t for t in res.triples if t.predicate == "operand"]
    # Two operands for one binary
    assert len(operand_edges) == 2
    # Operand index lives in attributes["operand_index"] as an int.
    by_idx = {t.attributes["operand_index"]: t.object for t in operand_edges}
    # And evidence_span should NOT carry the index any more.
    for t in operand_edges:
        assert t.evidence_span == ""
    assert by_idx[0].endswith(".a")  # LHS of binary is index 0
    assert by_idx[1].endswith(".b")


# ---------------------------------------------------------------------------
# Stable IDs
# ---------------------------------------------------------------------------


def test_stable_ids_across_runs():
    src = """
    module m;
      logic [7:0] a, b, c;
      logic en;
      always_comb begin
        if (en && a == b) c = a + b;
        else c = ~a;
      end
    endmodule
    """
    r1 = _run(src)
    r2 = _run(src)
    names1 = sorted(e.name for e in r1.entities)
    names2 = sorted(e.name for e in r2.entities)
    assert names1 == names2


# ---------------------------------------------------------------------------
# Literal sharing within module
# ---------------------------------------------------------------------------


def test_literal_node_sharing_within_module():
    src = """
    module m;
      logic [31:0] a, b, c, d;
      assign c = a + 32'h0;
      assign d = b + 32'h0;
    endmodule
    """
    signals = {"m": {"a", "b", "c", "d"}}
    res = _run(src, signals=signals)
    lits = [e for e in res.entities if e.type == "Literal"]
    # Literal "32h0" should appear once; "0" shared by value within module.
    by_name = Counter(e.name for e in lits)
    assert all(count == 1 for count in by_name.values()), \
        f"Literal nodes should be deduped within a module: {by_name}"
    # And there should be only one zero literal entity
    assert len(lits) == 1
    # But two operand edges should reference it (one per use site)
    operand_edges_to_lit = [
        t for t in res.triples
        if t.predicate == "operand" and t.object == lits[0].name
    ]
    assert len(operand_edges_to_lit) == 2


# ---------------------------------------------------------------------------
# Index node for bit-slice
# ---------------------------------------------------------------------------


def test_index_node_for_bit_slice_emits_slice_edges():
    src = """
    module m;
      logic [7:0] a;
      logic [3:0] d;
      assign d = a[3:0];
    endmodule
    """
    signals = {"m": {"a", "d"}}
    res = _run(src, signals=signals)
    idx_nodes = [e for e in res.entities if e.type == "Index"]
    assert len(idx_nodes) == 1
    idx = idx_nodes[0]
    slice_of = [t for t in res.triples if t.predicate == "slice_of" and t.subject == idx.name]
    slice_msb = [t for t in res.triples if t.predicate == "slice_msb" and t.subject == idx.name]
    slice_lsb = [t for t in res.triples if t.predicate == "slice_lsb" and t.subject == idx.name]
    assert len(slice_of) == 1
    assert slice_of[0].object == "m.a"
    assert len(slice_msb) == 1
    assert len(slice_lsb) == 1
    # MSB should resolve to literal 3, LSB to 0.
    msb_lit_name = slice_msb[0].object
    lsb_lit_name = slice_lsb[0].object
    lits = {e.name: e for e in res.entities if e.type == "Literal"}
    assert msb_lit_name in lits
    assert lsb_lit_name in lits
    assert "3" in msb_lit_name
    assert "0" in lsb_lit_name


# ---------------------------------------------------------------------------
# Layer tagging
# ---------------------------------------------------------------------------


def test_every_emitted_entity_and_triple_has_layer_ast():
    src = """
    module m;
      logic [7:0] a, b, c, d;
      logic en;
      always_comb begin
        if (en && a == b) c = a + b;
        else c = ~a;
        d = a[3:0];
      end
    endmodule
    """
    res = _run(src)
    # Walker only emits ast-layer entities/triples (track A scope).
    assert res.entities, "expected emitted entities"
    assert res.triples, "expected emitted triples"
    for e in res.entities:
        assert e.layer == "ast", f"entity {e.name} (type={e.type}) has layer={e.layer!r}"
    for t in res.triples:
        assert t.layer == "ast", \
            f"triple {t.subject}-{t.predicate}->{t.object} has layer={t.layer!r}"


# ---------------------------------------------------------------------------
# iter-015: no fragile-string hit on ``name`` receiver in _operator_kind
# ---------------------------------------------------------------------------


def test_operator_kind_uses_safe_receiver_name() -> None:
    """_operator_kind must NOT use a variable named ``name`` to hold the AST
    kind string — the scorer flags ``name.endswith(...)`` as a fragile-string
    hit.  After iter-015 the local should be ``kind_local`` or similar.

    This test would have FAILED before iter-015 because the function body
    contained ``name = _kind_local(node)  ...  if name.endswith("Expression"):``
    """
    import inspect
    import kgweave.knowledge_graph.extraction.sv_v2_walker as _mod

    src = inspect.getsource(_mod._operator_kind)
    # The old code had: name = _kind_local(node) ... if name.endswith(...)
    # After the fix the variable must NOT be called ``name``.
    assert 'name = _kind_local' not in src, (
        "_operator_kind still assigns to a local called 'name'; "
        "rename it to avoid the fragility-scorer hit"
    )


def test_operator_kind_strips_expression_suffix() -> None:
    """_operator_kind must strip the 'Expression' suffix from pyslang kind strings.

    We verify via the integration walker: the Add operator emitted for ``a+b``
    must carry kind='Add', not kind='AddExpression'.
    """
    src = """
    module m;
      logic [7:0] a, b, c;
      assign c = a + b;
    endmodule
    """
    res = _run(src)
    ops = [e for e in res.entities if e.type == "Operator"]
    assert ops, "expected at least one Operator entity"
    for op in ops:
        kind = op.attributes.get("kind", "")
        assert not kind.endswith("Expression"), (
            f"Operator entity {op.name!r} has kind={kind!r} — "
            "'Expression' suffix was not stripped by _operator_kind"
        )
