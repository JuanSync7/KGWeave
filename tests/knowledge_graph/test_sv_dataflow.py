"""Tests for the intra-module dataflow extractor (v1).

The extractor walks pyslang's syntax tree only (no elaboration) and emits:

* ``drives_signal(<module>.<src>, <module>.<dst>)`` — RHS identifier drives LHS.
* ``Process`` entities — one per always_* block / continuous-assign group.
* ``assigned_in(<module>.<dst>, <module>.<process_id>)`` — anchors target
  signal to the writing process.

v1 scope is whole-signal, intra-module only. See module docstring of
``sv_dataflow_extractor.py`` for the full v1 contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Set

import pytest

pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")

from kgweave.knowledge_graph.common import Triple
from kgweave.knowledge_graph.extraction.sv_dataflow_extractor import (
    SVDataflowExtractor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _module_signals_from_text(text: str) -> Dict[str, Set[str]]:
    """Best-effort: glean module signal table from text via SVParserExtractor."""
    from kgweave.knowledge_graph.extraction import SVParserExtractor
    from kgweave.knowledge_graph.common import KGConfig, load_schema

    schema_path = Path(__file__).resolve().parents[2] / "config" / "kg_schema.yaml"
    schema = load_schema(str(schema_path))
    cfg = KGConfig()
    parser = SVParserExtractor(schema=schema, config=cfg)
    res = parser.extract(text)
    table: Dict[str, Set[str]] = {}
    for ent in res.entities:
        if ent.type == "RTL_Module":
            table.setdefault(ent.name, set())
        elif "." in ent.name and ent.type in ("Port", "Signal"):
            mod, sig = ent.name.split(".", 1)
            table.setdefault(mod, set()).add(sig)
    return table


def _run(text: str) -> tuple[list, list]:
    table = _module_signals_from_text(text)
    extractor = SVDataflowExtractor(known_module_signals=table)
    res = extractor.extract(text=text, source="test.sv")
    return res.entities, res.triples


def _drives_pairs(triples: list[Triple]) -> set[tuple[str, str]]:
    return {(t.subject, t.object) for t in triples if t.predicate == "drives_signal"}


def _assigned_in_pairs(triples: list[Triple]) -> set[tuple[str, str]]:
    return {(t.subject, t.object) for t in triples if t.predicate == "assigned_in"}


# ---------------------------------------------------------------------------
# Cycle A — basic continuous-assign
# ---------------------------------------------------------------------------


def test_continuous_assign_emits_drives_signal() -> None:
    src = """
    module m(input a, output y);
      assign y = a;
    endmodule
    """
    _entities, triples = _run(src)
    assert ("m.a", "m.y") in _drives_pairs(triples)


def test_continuous_assign_with_combinational_logic() -> None:
    src = """
    module m(input a, input b, output y);
      assign y = a & b;
    endmodule
    """
    _entities, triples = _run(src)
    pairs = _drives_pairs(triples)
    assert ("m.a", "m.y") in pairs
    assert ("m.b", "m.y") in pairs


# ---------------------------------------------------------------------------
# Cycle B — always_ff / always_comb LHS targets
# ---------------------------------------------------------------------------


def test_always_ff_lhs_target_drives_from_rhs_identifiers() -> None:
    src = """
    module m(input clk, input d, output logic q);
      always_ff @(posedge clk) q <= d;
    endmodule
    """
    _e, triples = _run(src)
    pairs = _drives_pairs(triples)
    assert ("m.d", "m.q") in pairs
    # v1 spec: clock identifier is a RHS NamedValue and counts.
    assert ("m.clk", "m.q") in pairs


# ---------------------------------------------------------------------------
# Cycle C — branches; dedup
# ---------------------------------------------------------------------------


def test_always_comb_with_branches_collects_all_lhs() -> None:
    src = """
    module m(input cond, input a, input b, output logic y);
      always_comb begin
        if (cond) y = a;
        else      y = b;
      end
    endmodule
    """
    _e, triples = _run(src)
    pairs = _drives_pairs(triples)
    assert ("m.cond", "m.y") in pairs
    assert ("m.a", "m.y") in pairs
    assert ("m.b", "m.y") in pairs


def test_dedup_multiple_assignments_to_same_pair() -> None:
    src = """
    module m(input a, output logic y);
      assign y = a;
      always_comb y = a;
    endmodule
    """
    entities, triples = _run(src)
    drives = [t for t in triples if t.predicate == "drives_signal"
              and (t.subject, t.object) == ("m.a", "m.y")]
    assert len(drives) == 1, f"expected single deduped triple, got {len(drives)}"
    # Both processes still emit assigned_in to m.y.
    ai = _assigned_in_pairs(triples)
    procs_for_y = {p for (s, p) in ai if s == "m.y"}
    assert len(procs_for_y) == 2


# ---------------------------------------------------------------------------
# Cycle D — heuristics
# ---------------------------------------------------------------------------


def test_bit_slice_lhs_collapses_to_base_signal() -> None:
    src = """
    module m(input a, output logic [7:0] x);
      always_comb x[3:0] = a;
    endmodule
    """
    _e, triples = _run(src)
    pairs = _drives_pairs(triples)
    assert ("m.a", "m.x") in pairs
    # No bracketed target name should appear.
    for s, o in pairs:
        assert "[" not in s and "[" not in o


def test_loop_variable_not_in_graph() -> None:
    src = """
    module m(input [3:0] a, output logic [3:0] y);
      always_comb begin
        for (int i = 0; i < 4; i++) y[i] = a[i];
      end
    endmodule
    """
    _e, triples = _run(src)
    pairs = _drives_pairs(triples)
    # The loop var i is not a module signal — must not appear.
    for s, o in pairs:
        assert s != "m.i" and o != "m.i"
    # a -> y is the meaningful drive.
    assert ("m.a", "m.y") in pairs


def test_function_call_in_rhs_is_not_a_driver() -> None:
    src = """
    module m(input a, output logic y);
      function automatic logic my_func(input logic x);
        return ~x;
      endfunction
      assign y = my_func(a);
    endmodule
    """
    _e, triples = _run(src)
    pairs = _drives_pairs(triples)
    assert ("m.a", "m.y") in pairs
    # my_func is not a module signal so cannot appear.
    for s, o in pairs:
        assert s != "m.my_func"


def test_unknown_identifier_not_emitted() -> None:
    src = """
    module m(output logic y);
      assign y = some_pkg::CONST + other_unknown;
    endmodule
    """
    _e, triples = _run(src)
    pairs = _drives_pairs(triples)
    # No source resolves to a module signal — graph stays clean.
    assert not any(o == "m.y" for s, o in pairs)


# ---------------------------------------------------------------------------
# Cycle E — Process entities + assigned_in
# ---------------------------------------------------------------------------


def test_process_entity_emitted_per_always_block() -> None:
    src = """
    module m(input clk, input d, input a, output logic q, output logic y);
      always_ff @(posedge clk) q <= d;
      always_comb y = a;
    endmodule
    """
    entities, _t = _run(src)
    proc_names = {e.name for e in entities if e.type == "Process"}
    assert "m.always_ff_0" in proc_names
    assert "m.always_comb_1" in proc_names


def test_assigned_in_anchors_lhs_to_process() -> None:
    src = """
    module m(input clk, input d, output logic q);
      always_ff @(posedge clk) q <= d;
    endmodule
    """
    _e, triples = _run(src)
    ai = _assigned_in_pairs(triples)
    assert ("m.q", "m.always_ff_0") in ai


def test_continuous_assign_emits_process_entity() -> None:
    src = """
    module m(input a, output y);
      assign y = a;
    endmodule
    """
    entities, triples = _run(src)
    proc_names = {e.name for e in entities if e.type == "Process"}
    assert "m.assign_0" in proc_names
    ai = _assigned_in_pairs(triples)
    assert ("m.y", "m.assign_0") in ai


# ---------------------------------------------------------------------------
# Cycle F — module-boundary; generate
# ---------------------------------------------------------------------------


def test_module_boundary_not_crossed() -> None:
    src = """
    module child(input x, output o);
      assign o = x;
    endmodule

    module m(input my_sig, output q);
      child u_c(.x(my_sig), .o(q));
    endmodule
    """
    _e, triples = _run(src)
    pairs = _drives_pairs(triples)
    # Cross-module edge must not appear.
    for s, o in pairs:
        # Allow only same-module endpoints.
        assert s.split(".", 1)[0] == o.split(".", 1)[0], \
            f"unexpected cross-module drive: {s} -> {o}"


def test_generate_block_body_walked() -> None:
    src = """
    module m(input [3:0] a, output logic [3:0] y);
      genvar gi;
      generate
        for (gi = 0; gi < 4; gi = gi + 1) begin : g
          assign y[gi] = a[gi];
        end
      endgenerate
    endmodule
    """
    _e, triples = _run(src)
    pairs = _drives_pairs(triples)
    # Drive should surface scoped to m.* (collapsed across iterations).
    assert ("m.a", "m.y") in pairs


# ---------------------------------------------------------------------------
# Cycle G — real OpenTitan AES file (best-effort smoke)
# ---------------------------------------------------------------------------


def _candidate_aes_files() -> list[Path]:
    import os
    roots = [
        Path(os.environ.get("KGWEAVE_OPENTITAN_ROOT", "")),
        Path.home() / "RagWeave" / "opentitan_data",
        Path(__file__).resolve().parents[2] / "data" / "opentitan",
    ]
    rels = [
        "hw/ip/aes/rtl/aes_cipher_core.sv",
        "hw/ip/aes/rtl/aes_core.sv",
        "hw/ip/aes/rtl/aes_control.sv",
        "hw/ip/aes/rtl/aes_ctr.sv",
    ]
    found: list[Path] = []
    for root in roots:
        if not root or not root.exists():
            continue
        for rel in rels:
            p = root / rel
            if p.is_file():
                found.append(p)
    return found


def test_full_suite_demo_dataset_aes_module() -> None:
    files = _candidate_aes_files()
    if not files:
        pytest.skip("OpenTitan AES dataset not present locally")
    text = files[0].read_text(encoding="utf-8", errors="replace")
    table = _module_signals_from_text(text)
    if not table:
        pytest.skip("AES file produced no signal table")
    extractor = SVDataflowExtractor(known_module_signals=table)
    res = extractor.extract(text=text, source=str(files[0]))
    drives = [t for t in res.triples if t.predicate == "drives_signal"]
    assert drives, "expected at least one drives_signal triple from real AES file"


# ---------------------------------------------------------------------------
# Defensive: empty signal table behaviour
# ---------------------------------------------------------------------------


def test_empty_signal_table_raises() -> None:
    extractor = SVDataflowExtractor(known_module_signals={})
    with pytest.raises(ValueError):
        extractor.extract(
            text="module m(input a, output y); assign y = a; endmodule",
            source="x.sv",
        )
