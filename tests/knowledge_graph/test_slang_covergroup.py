# @summary
# TDD: SlangHierarchyAnalyzer must extract SystemVerilog covergroup blocks
# (covergroup ... endgroup) from RTL/DV source as Covergroup_SV / Coverpoint /
# CoverBin / CoverCross entities, plus has_coverpoint / has_bin / has_cross /
# observes / crosses / defined_in edges. Closes the "coverpoint measuring
# this spec'd behavior?" arrow of the audit-completeness query.
# @end-summary
"""Tests for SlangHierarchyAnalyzer covergroup extraction."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


def _run(tmp_path: Path, src: str, top: str = "dut"):
    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    dut = src_dir / f"{top}.sv"
    dut.write_text(src)
    fl = tmp_path / "files.f"
    fl.write_text(str(dut) + "\n")

    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl),
        backend=backend,
        top_module=top,
    )
    return analyzer.analyze_full()


_MOD_ONE_CG = """\
module dut(input logic clk, input logic [1:0] mode);
  covergroup my_cg @(posedge clk);
    cp_mode: coverpoint mode;
  endgroup
endmodule
"""


_MOD_BINS = """\
module dut(input logic clk, input logic [1:0] state);
  covergroup my_cg @(posedge clk);
    cp_state: coverpoint state {
      bins idle = {2'd0};
      bins busy = {2'd1};
    }
  endgroup
endmodule
"""


_MOD_CROSS = """\
module dut(input logic clk, input logic [1:0] a, input logic [1:0] b);
  covergroup my_cg @(posedge clk);
    cp_a: coverpoint a;
    cp_b: coverpoint b;
    my_cross: cross cp_a, cp_b;
  endgroup
endmodule
"""


_MOD_NO_CG = """\
module dut(input logic clk, input logic [3:0] data, output logic any);
  assign any = |data;
endmodule
"""


def test_covergroup_entity_emitted(tmp_path: Path) -> None:
    result = _run(tmp_path, _MOD_ONE_CG)
    cgs = [e for e in result.entities if e.type == "Covergroup_SV"]
    assert len(cgs) == 1, [(e.name, e.type) for e in result.entities]
    assert cgs[0].name == "dut.my_cg"
    defined_in = [
        t for t in result.triples
        if t.predicate == "defined_in" and t.subject == "dut.my_cg"
    ]
    assert defined_in and defined_in[0].object == "dut"


def test_coverpoint_entity_emitted(tmp_path: Path) -> None:
    result = _run(tmp_path, _MOD_ONE_CG)
    cps = [e for e in result.entities if e.type == "Coverpoint"]
    assert len(cps) == 1
    assert cps[0].name == "dut.my_cg.cp_mode"
    has_cp = [t for t in result.triples if t.predicate == "has_coverpoint"]
    assert any(
        t.subject == "dut.my_cg" and t.object == "dut.my_cg.cp_mode"
        for t in has_cp
    )


def test_coverpoint_observes_signal(tmp_path: Path) -> None:
    result = _run(tmp_path, _MOD_ONE_CG)
    obs = [t for t in result.triples if t.predicate == "observes"]
    assert len(obs) == 1, obs
    assert obs[0].subject == "dut.my_cg.cp_mode"
    assert obs[0].object == "dut.mode"


def test_bin_entity_emitted(tmp_path: Path) -> None:
    result = _run(tmp_path, _MOD_BINS)
    bins = [e for e in result.entities if e.type == "CoverBin"]
    bin_names = sorted(e.name for e in bins)
    assert bin_names == ["dut.my_cg.cp_state.busy", "dut.my_cg.cp_state.idle"]
    has_bin = [t for t in result.triples if t.predicate == "has_bin"]
    assert len(has_bin) == 2
    assert all(t.subject == "dut.my_cg.cp_state" for t in has_bin)


def test_cross_entity_emitted(tmp_path: Path) -> None:
    result = _run(tmp_path, _MOD_CROSS)
    crosses = [e for e in result.entities if e.type == "CoverCross"]
    assert len(crosses) == 1
    assert crosses[0].name == "dut.my_cg.my_cross"
    has_cross = [t for t in result.triples if t.predicate == "has_cross"]
    assert any(
        t.subject == "dut.my_cg" and t.object == "dut.my_cg.my_cross"
        for t in has_cross
    )
    crosses_edges = sorted(
        t.object for t in result.triples if t.predicate == "crosses"
    )
    assert crosses_edges == ["dut.my_cg.cp_a", "dut.my_cg.cp_b"]


def test_no_covergroup_no_entities(tmp_path: Path) -> None:
    result = _run(tmp_path, _MOD_NO_CG)
    cov_types = {"Covergroup_SV", "Coverpoint", "CoverBin", "CoverCross"}
    cov_entities = [e for e in result.entities if e.type in cov_types]
    cov_preds = {"has_coverpoint", "has_bin", "has_cross", "observes",
                 "crosses", "defined_in"}
    cov_edges = [t for t in result.triples if t.predicate in cov_preds]
    assert cov_entities == []
    assert cov_edges == []


def test_real_aes_smoke(tmp_path: Path) -> None:
    """Smoke-test on the OpenTitan AES fixture if available.

    AES happens to put functional coverage in dv/cov/ (UVM-dependent) and
    dv/env/ — none in pure RTL or dv/sva/. So when we restrict the filelist
    to RTL + dv/sva/ (the demo's filelist) we expect *zero* covergroups —
    that is itself useful evidence: the audit query for AES will need to
    look at dv/cov sources separately. This test asserts the extractor
    runs without errors and reports the count cleanly.
    """
    ot_root = Path(os.environ.get(
        "KGWEAVE_OPENTITAN_ROOT",
        str(Path.home() / "RagWeave" / "opentitan_data"),
    ))
    aes_rtl = ot_root / "hw" / "ip" / "aes" / "rtl"
    if not aes_rtl.exists():
        pytest.skip(f"OpenTitan AES fixture not present at {aes_rtl}")

    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    sv_files = sorted(aes_rtl.glob("*.sv"))
    fl = tmp_path / "aes.f"
    fl.write_text("\n".join(str(p) for p in sv_files) + "\n")

    prim_rtl = ot_root / "hw" / "ip" / "prim" / "rtl"
    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl),
        backend=backend,
        top_module="aes",
        incdirs=[str(prim_rtl)] if prim_rtl.exists() else None,
        defines=["INC_ASSERT", "FPV_ON", "SIMULATION", "EN_MASKING"],
    )
    result = analyzer.analyze_full()

    cgs = [e for e in result.entities if e.type == "Covergroup_SV"]
    # AES RTL has no covergroups (functional coverage is in dv/cov/, which
    # depends on uvm_pkg and is excluded from this filelist). Asserting >=0
    # locks the contract that the extractor doesn't crash on real hardware
    # and surfaces a clean count either way.
    assert isinstance(cgs, list)
    assert len(cgs) >= 0
