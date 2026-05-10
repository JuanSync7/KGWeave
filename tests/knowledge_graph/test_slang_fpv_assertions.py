# @summary
# TDD: SlangHierarchyAnalyzer must respect compile-time guard macros so that
# assertions hidden behind `\`ifdef FPV_ON`, `\`ifndef SYNTHESIS`, sec-cm
# guards, and similar gating get surfaced when the corresponding predefines
# are passed via the `defines=` constructor argument. Locks the contract that
# the same source emits different assertion counts depending on the predefine
# set.
# @end-summary
"""Tests for SlangHierarchyAnalyzer FPV / sec-cm / synthesis guard plumbing."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


SV_FPV_ONLY = """\
module dut_fpv(
    input  logic clk_i,
    input  logic rst_ni,
    input  logic a_i,
    input  logic b_i
);
`ifdef FPV_ON
    fpv_only_a: assert property (@(posedge clk_i) disable iff (!rst_ni) a_i |-> b_i);
`endif
endmodule
"""


SV_SYNTHESIS_GUARD = """\
module dut_synth(
    input  logic clk_i,
    input  logic rst_ni,
    input  logic a_i
);
`ifndef SYNTHESIS
    not_synth_a: assert property (@(posedge clk_i) disable iff (!rst_ni) a_i);
`endif
endmodule
"""


SV_NESTED_GUARDS = """\
module dut_nested(
    input  logic clk_i,
    input  logic rst_ni,
    input  logic a_i,
    input  logic b_i,
    input  logic c_i
);
`ifdef INC_ASSERT
    inc_a: assert property (@(posedge clk_i) disable iff (!rst_ni) a_i);

  `ifdef FPV_ON
    fpv_a: assert property (@(posedge clk_i) disable iff (!rst_ni) b_i);

    `ifdef SEC_CM_ON
    seccm_a: assert property (@(posedge clk_i) disable iff (!rst_ni) c_i);
    `endif
  `endif
`endif
endmodule
"""


def _run(tmp_path: Path, src: str, top: str, defines):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    dut = src_dir / f"{top}.sv"
    dut.write_text(src)
    fl = tmp_path / "files.f"
    fl.write_text(str(dut) + "\n")

    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl),
        backend=backend,
        top_module=top,
        defines=defines,
    )
    return analyzer.analyze_full()


def test_fpv_on_assertions_extracted(tmp_path: Path) -> None:
    """`\\`ifdef FPV_ON` body expands only when FPV_ON is predefined."""
    without = _run(tmp_path / "a", SV_FPV_ONLY, "dut_fpv", defines=[])
    with_fpv = _run(tmp_path / "b", SV_FPV_ONLY, "dut_fpv", defines=["FPV_ON"])

    n_without = sum(1 for e in without.entities if e.type == "SVA_Assertion")
    n_with = sum(1 for e in with_fpv.entities if e.type == "SVA_Assertion")

    assert n_without == 0, f"expected 0 without FPV_ON, got {n_without}"
    assert n_with == 1, f"expected 1 with FPV_ON, got {n_with}"


def test_synthesis_guard_inverted(tmp_path: Path) -> None:
    """`\\`ifndef SYNTHESIS` body is active when SYNTHESIS is *not* defined."""
    default_run = _run(tmp_path / "a", SV_SYNTHESIS_GUARD, "dut_synth", defines=[])
    synth_run = _run(tmp_path / "b", SV_SYNTHESIS_GUARD, "dut_synth", defines=["SYNTHESIS"])

    n_default = sum(1 for e in default_run.entities if e.type == "SVA_Assertion")
    n_synth = sum(1 for e in synth_run.entities if e.type == "SVA_Assertion")

    assert n_default == 1, f"expected 1 with SYNTHESIS undefined, got {n_default}"
    assert n_synth == 0, f"expected 0 with SYNTHESIS defined, got {n_synth}"


def test_multiple_guards_combined(tmp_path: Path) -> None:
    """Independent flat guards: count is the sum of enabled bodies."""
    src = """\
module dut_multi(
    input  logic clk_i,
    input  logic rst_ni,
    input  logic a_i,
    input  logic b_i,
    input  logic c_i
);
`ifdef INC_ASSERT
    inc_a: assert property (@(posedge clk_i) disable iff (!rst_ni) a_i);
`endif
`ifdef FPV_ON
    fpv_a: assert property (@(posedge clk_i) disable iff (!rst_ni) b_i);
`endif
`ifdef SEC_CM_ON
    seccm_a: assert property (@(posedge clk_i) disable iff (!rst_ni) c_i);
`endif
endmodule
"""
    none = _run(tmp_path / "a", src, "dut_multi", defines=[])
    all_three = _run(
        tmp_path / "b", src, "dut_multi",
        defines=["INC_ASSERT", "FPV_ON", "SEC_CM_ON"],
    )

    assert sum(1 for e in none.entities if e.type == "SVA_Assertion") == 0
    assert sum(1 for e in all_three.entities if e.type == "SVA_Assertion") == 3


def test_nested_guards_require_all_enclosing(tmp_path: Path) -> None:
    """A nested assertion only expands when every enclosing guard is set."""
    base = _run(tmp_path / "a", SV_NESTED_GUARDS, "dut_nested",
                defines=["INC_ASSERT"])
    plus_fpv = _run(tmp_path / "b", SV_NESTED_GUARDS, "dut_nested",
                    defines=["INC_ASSERT", "FPV_ON"])
    plus_all = _run(tmp_path / "c", SV_NESTED_GUARDS, "dut_nested",
                    defines=["INC_ASSERT", "FPV_ON", "SEC_CM_ON"])

    assert sum(1 for e in base.entities if e.type == "SVA_Assertion") == 1
    assert sum(1 for e in plus_fpv.entities if e.type == "SVA_Assertion") == 2
    assert sum(1 for e in plus_all.entities if e.type == "SVA_Assertion") == 3
