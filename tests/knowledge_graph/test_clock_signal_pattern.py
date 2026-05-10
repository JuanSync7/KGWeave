"""Phase 3 D12 — clock_signal_pattern positive-match in SlangHierarchyAnalyzer.

When the user supplies ``clock_signal_pattern``, only signals matching it
(and not matching the reset regex) are emitted as ``clocked_by``. Signals
neither matching the reset pattern nor the clock pattern produce no edge.

These tests use generic non-OT clock names (``pclk``, ``hclk``) so the
behavior is exercised independently of the OT default reset heuristic.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backend import GraphStorageBackend
from kgweave.knowledge_graph.extraction.sv_connectivity import (
    SlangHierarchyAnalyzer,
)


def _make_backend() -> GraphStorageBackend:
    from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
    return NetworkXBackend()


SYNTHETIC_TWO_CLOCKS = textwrap.dedent(
    """\
    module gizmo_ahb (
        input  logic pclk,
        input  logic hclk,
        input  logic rst_n,
        input  logic [7:0] din,
        output logic [7:0] dout
    );
        logic [7:0] q1, q2;
        always_ff @(posedge pclk or negedge rst_n) begin
            if (!rst_n) q1 <= 8'h00;
            else        q1 <= din;
        end
        always_ff @(posedge hclk or negedge rst_n) begin
            if (!rst_n) q2 <= 8'h00;
            else        q2 <= q1;
        end
        assign dout = q2;
    endmodule
    """
)


# ---- Unit: clock_signal_pattern compiles and is exposed -------------------


def test_clock_signal_pattern_compiles_and_is_stored():
    """Constructor accepts the pattern and stores a compiled regex."""
    backend = _make_backend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path="/nonexistent.f",
        backend=backend,
        clock_signal_pattern=r"^[ph]clk$",
    )
    assert analyzer._clock_re is not None
    assert analyzer._clock_re.search("pclk")
    assert analyzer._clock_re.search("hclk")
    assert not analyzer._clock_re.search("data_in")


# ---- Integration: clock_signal_pattern restricts clocked_by emissions -----


def _write_filelist(tmp_path: Path) -> Path:
    sv_path = tmp_path / "gizmo_ahb.sv"
    sv_path.write_text(SYNTHETIC_TWO_CLOCKS)
    fl = tmp_path / "gizmo.f"
    fl.write_text(str(sv_path) + "\n")
    return fl


def test_clock_signal_pattern_emits_only_matching_clocks(tmp_path):
    """With clock_signal_pattern set, only ``pclk`` / ``hclk`` count as
    clocks. (Synthetic module has only those, so this primarily verifies
    that the gating doesn't regress legacy detection.)"""
    fl = _write_filelist(tmp_path)
    backend = _make_backend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl),
        backend=backend,
        top_module="gizmo_ahb",
        clock_signal_pattern=r"^(pclk|hclk)$",
    )
    triples = analyzer.analyze()
    clocked = {t.object for t in triples if t.predicate == "clocked_by"}
    reset = {t.object for t in triples if t.predicate == "reset_by"}
    assert "pclk" in clocked
    assert "hclk" in clocked
    # rst_n must be classified as a reset, not a clock.
    assert "rst_n" not in clocked
    assert "rst_n" in reset
