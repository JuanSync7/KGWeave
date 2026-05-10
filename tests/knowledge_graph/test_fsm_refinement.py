# @summary
# TDD: refined FSM extraction.
# Tightens FSM detection (enum vars only count if used as case selector or in
# an if-ladder condition) and broadens transition detection (priority if/else-if
# next-state ladders inside always_comb produce transitions_to edges).
# @end-summary
"""Tests for FSM refinement in SlangHierarchyAnalyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.common import Triple
from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


def _write_filelist(tmp_path: Path, files: dict[str, str]) -> Path:
    paths = []
    for name, content in files.items():
        p = tmp_path / name
        p.write_text(content)
        paths.append(p.name)
    fl = tmp_path / "files.f"
    fl.write_text("\n".join(paths) + "\n")
    return fl


def _run(tmp_path: Path, src: str, top: str = "dut"):
    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    fl = _write_filelist(tmp_path, {f"{top}.sv": src})
    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl), backend=backend, top_module=top,
    )
    return backend, analyzer.analyze_full()


class TestFSMRefinement:
    def test_data_only_enum_var_is_not_fsm(self, tmp_path: Path) -> None:
        """An enum-typed Variable that is NOT used as a case selector or in
        any if-condition must NOT be promoted to an FSM. It's just data.
        """
        src = """
        module dut(input logic clk, input logic rst_n, output logic [1:0] cfg_o);
          typedef enum logic [1:0] { CFG_A, CFG_B, CFG_C } cfg_e;
          cfg_e cfg_q, cfg_d;
          always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) cfg_q <= CFG_A;
            else        cfg_q <= cfg_d;
          end
          // cfg_d is just data — never inspected, never used as a selector.
          assign cfg_d = CFG_B;
          assign cfg_o = cfg_q;
        endmodule
        """
        _, result = _run(tmp_path, src)
        fsms = [e for e in result.entities if e.type == "FSM"]
        assert fsms == [], (
            f"Expected NO FSMs (enum var is data-only), got {[e.name for e in fsms]}"
        )

    def test_enum_used_as_case_selector_is_fsm(self, tmp_path: Path) -> None:
        src = """
        module dut(input logic clk, input logic rst_n, output logic done);
          typedef enum logic [1:0] { S_IDLE, S_RUN, S_FIN } st_e;
          st_e cs, ns;
          always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) cs <= S_IDLE;
            else        cs <= ns;
          end
          always_comb begin
            ns = cs;
            case (cs)
              S_IDLE: ns = S_RUN;
              S_RUN:  ns = S_FIN;
              S_FIN:  ns = S_IDLE;
            endcase
          end
          assign done = (cs == S_FIN);
        endmodule
        """
        _, result = _run(tmp_path, src)
        fsms = {e.name for e in result.entities if e.type == "FSM"}
        assert "dut.fsm_cs" in fsms, f"Expected dut.fsm_cs, got {fsms}"

    def test_enum_used_in_if_ladder_is_fsm(self, tmp_path: Path) -> None:
        """Enum var used in `if (cs == STATE)` qualifies as FSM even with
        no case statement.
        """
        src = """
        module dut(input logic clk, input logic rst_n);
          typedef enum logic [1:0] { S_A, S_B, S_C } st_e;
          st_e cs, ns;
          always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) cs <= S_A;
            else        cs <= ns;
          end
          always_comb begin
            ns = cs;
            if (cs == S_A) ns = S_B;
            else if (cs == S_B) ns = S_C;
            else ns = S_A;
          end
        endmodule
        """
        _, result = _run(tmp_path, src)
        fsms = {e.name for e in result.entities if e.type == "FSM"}
        assert "dut.fsm_cs" in fsms, f"Expected dut.fsm_cs, got {fsms}"

    def test_priority_ladder_emits_transitions(self, tmp_path: Path) -> None:
        """An if/else-if ladder assigning constant enum literals to the
        next-state variable must produce transitions_to edges — one per
        distinct RHS literal.
        """
        src = """
        module dut(input logic clk, input logic rst_n,
                   input logic cond_x, input logic cond_y);
          typedef enum logic [1:0] { S_X, S_Y, S_Z } st_e;
          st_e cs, ns;
          always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) cs <= S_Z;
            else        cs <= ns;
          end
          always_comb begin
            if (cond_x)      ns = S_X;
            else if (cond_y) ns = S_Y;
            else             ns = S_Z;
          end
          // Force FSM detection: use cs in an if-condition somewhere.
          logic flag;
          always_comb begin
            flag = 1'b0;
            if (cs == S_X) flag = 1'b1;
          end
        endmodule
        """
        _, result = _run(tmp_path, src)
        transitions = [t for t in result.triples if t.predicate == "transitions_to"]
        dsts = {t.object for t in transitions}
        assert "dut.S_X" in dsts and "dut.S_Y" in dsts and "dut.S_Z" in dsts, (
            f"Expected transitions to S_X/S_Y/S_Z, got {dsts}"
        )
        # At least 3 distinct destinations from the ladder.
        assert len({(t.subject, t.object) for t in transitions}) >= 3, (
            f"Expected >=3 transitions, got {[(t.subject,t.object) for t in transitions]}"
        )
