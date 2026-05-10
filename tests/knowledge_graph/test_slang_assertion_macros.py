# @summary
# TDD: SlangHierarchyAnalyzer must support `+incdir+` paths and `+define+`
# macros so that OpenTitan-style `\`include "prim_assert.sv"` + `\`ASSERT(...)`
# usage expands to actual `assert property` syntax during elaboration. Without
# this, downstream `_emit_assertion_edges` sees zero assertions even though
# the source uses them heavily via macros.
# @end-summary
"""Tests for SlangHierarchyAnalyzer include-dir + predefine plumbing."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


STUB_PRIM_ASSERT = """\
`ifndef PRIM_ASSERT_STUB_SVH
`define PRIM_ASSERT_STUB_SVH
`ifdef INC_ASSERT
`define ASSERT(__name, __prop, __clk, __rst) \\
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop));
`else
`define ASSERT(__name, __prop, __clk, __rst)
`endif
`endif
"""


SV_MODULE = """\
`include "prim_assert_stub.svh"

module dut(
    input  logic clk_i,
    input  logic rst_ni,
    input  logic [3:0] data_i,
    output logic       valid_o
);
    assign valid_o = |data_i;

    `ASSERT(ValidImpliesData_A, valid_o |-> (data_i != '0), clk_i, !rst_ni)
endmodule
"""


def test_analyzer_accepts_incdirs_and_defines(tmp_path: Path) -> None:
    """Macro-wrapped assertions must surface as SVA_Assertion entities."""
    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    inc_dir = tmp_path / "inc"
    inc_dir.mkdir()
    (inc_dir / "prim_assert_stub.svh").write_text(STUB_PRIM_ASSERT)

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dut = src_dir / "dut.sv"
    dut.write_text(SV_MODULE)

    fl = tmp_path / "files.f"
    fl.write_text(str(dut) + "\n")

    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl),
        backend=backend,
        top_module="dut",
        incdirs=[str(inc_dir)],
        defines=["INC_ASSERT"],
    )
    result = analyzer.analyze_full()

    sva_entities = [e for e in result.entities if e.type == "SVA_Assertion"]
    has_assertion = [t for t in result.triples if t.predicate == "has_assertion"]

    assert len(sva_entities) >= 1, (
        f"expected >=1 SVA_Assertion entity, got {len(sva_entities)}; "
        f"entities={[(e.name, e.type) for e in result.entities]}"
    )
    assert len(has_assertion) >= 1, (
        f"expected >=1 has_assertion edge, got {len(has_assertion)}"
    )
