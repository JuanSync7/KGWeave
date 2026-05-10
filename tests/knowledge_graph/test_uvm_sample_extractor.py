"""Tests for the UVM sample-callsite extractor (Gap #3 audit closure).

Five-cycle TDD progression:
  1 — direct ``<cg>_inst.sample(...)`` callsite detection
  2 — wrapper function discovery (``cg_X_sample`` -> covergroup name)
  3 — wrapper-callsite linking across files (via_wrapper + samples_covergroup)
  4 — argument-binding edges (UVMSampleArgExpr -> Covergroup_SampleArg)
  5 — AES end-to-end (skipped if RagWeave/opentitan_data is unavailable)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kgweave.knowledge_graph.extraction.uvm_sample_extractor import (
    UVMSampleExtractor,
    UVM_SAMPLE_SOURCE,
)


def _write(p: Path, body: str) -> Path:
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# Cycle 1 — direct call
# ---------------------------------------------------------------------------


class TestCycle1DirectCall:
    def test_direct_inst_sample_callsite_emitted(self, tmp_path: Path) -> None:
        sv = """
module m;
  covergroup cg with function sample(bit x);
    cp: coverpoint x;
  endgroup
  cg cg_inst = new();
  initial cg_inst.sample(1'b1);
endmodule
"""
        _write(tmp_path / "m.sv", sv)
        result = UVMSampleExtractor().extract_directory(tmp_path)
        callsites = [e for e in result.entities if e.type == "UVMSampleCallsite"]
        assert len(callsites) >= 1
        # samples_covergroup edge points at the bare stem `cg`
        edges = [t for t in result.triples if t.predicate == "samples_covergroup"]
        assert any(t.object == "cg" for t in edges)

    def test_layer_and_source_tagging(self, tmp_path: Path) -> None:
        sv = "module m; initial my_cg_inst.sample(1); endmodule\n"
        _write(tmp_path / "m.sv", sv)
        result = UVMSampleExtractor().extract_directory(tmp_path)
        for ent in result.entities:
            assert ent.layer == UVM_SAMPLE_SOURCE
            assert UVM_SAMPLE_SOURCE in ent.extractor_source
        for tr in result.triples:
            assert tr.layer == UVM_SAMPLE_SOURCE
            assert tr.extractor_source == UVM_SAMPLE_SOURCE


# ---------------------------------------------------------------------------
# Cycle 2 — wrapper discovery
# ---------------------------------------------------------------------------


class TestCycle2WrapperDiscovery:
    def test_wrapper_function_recorded(self, tmp_path: Path) -> None:
        sv = """
interface my_if;
  covergroup my_cg with function sample(bit x);
    cp: coverpoint x;
  endgroup
  my_cg my_cg_inst = new();
  function automatic void f_sample(bit x);
    my_cg_inst.sample(x);
  endfunction
endinterface
"""
        _write(tmp_path / "my_if.sv", sv)
        result = UVMSampleExtractor().extract_directory(tmp_path)
        wrappers = [e for e in result.entities if e.type == "UVMSampleWrapper"]
        assert len(wrappers) == 1
        w = wrappers[0]
        assert w.name == "my_if.sv::f_sample"
        # Aliases include the inner covergroup binding.
        assert any("inner_covergroup=my_cg" in a for a in w.aliases)
        # wraps_covergroup edge present
        wraps = [t for t in result.triples if t.predicate == "wraps_covergroup"]
        assert any(t.subject == w.name and t.object == "my_cg" for t in wraps)


# ---------------------------------------------------------------------------
# Cycle 3 — wrapper callsite across files
# ---------------------------------------------------------------------------


class TestCycle3WrapperCallsite:
    def test_callsite_resolves_via_wrapper(self, tmp_path: Path) -> None:
        cov_if = """
interface my_if;
  covergroup my_cg with function sample(bit x);
    cp: coverpoint x;
  endgroup
  my_cg my_cg_inst = new();
  function automatic void f_sample(bit x);
    my_cg_inst.sample(x);
  endfunction
endinterface
"""
        scoreboard = """
module sb;
  initial cov.f_sample(42);
endmodule
"""
        _write(tmp_path / "my_if.sv", cov_if)
        _write(tmp_path / "sb.sv", scoreboard)
        result = UVMSampleExtractor().extract_directory(tmp_path)

        # Callsite from sb.sv
        sb_callsites = [
            e for e in result.entities
            if e.type == "UVMSampleCallsite" and e.name.startswith("sb.sv::")
        ]
        assert len(sb_callsites) == 1
        cs = sb_callsites[0]

        # via_wrapper edge -> wrapper from my_if.sv
        via = [t for t in result.triples if t.predicate == "via_wrapper"
               and t.subject == cs.name]
        assert len(via) == 1
        assert via[0].object == "my_if.sv::f_sample"

        # samples_covergroup edge resolves through wrapper to my_cg
        samples = [t for t in result.triples if t.predicate == "samples_covergroup"
                   and t.subject == cs.name]
        assert len(samples) == 1
        assert samples[0].object == "my_cg"

    def test_wrapper_self_call_is_not_double_counted(self, tmp_path: Path) -> None:
        # The wrapper body itself contains a `_inst.sample()` invocation;
        # we should NOT also emit a direct-style callsite for it.
        cov_if = """
interface my_if;
  function automatic void f_sample(bit x);
    my_cg_inst.sample(x);
  endfunction
endinterface
"""
        scoreboard = """
module sb;
  initial cov.f_sample(7);
endmodule
"""
        _write(tmp_path / "my_if.sv", cov_if)
        _write(tmp_path / "sb.sv", scoreboard)
        result = UVMSampleExtractor().extract_directory(tmp_path)
        callsites = [e for e in result.entities if e.type == "UVMSampleCallsite"]
        assert len(callsites) == 1, [e.name for e in callsites]


# ---------------------------------------------------------------------------
# Cycle 4 — argument binding
# ---------------------------------------------------------------------------


class TestCycle4ArgumentBinding:
    def test_binds_to_arg_with_known_sample_args(self, tmp_path: Path) -> None:
        cov_if = """
interface my_if;
  function automatic void f_sample(bit x);
    my_cg_inst.sample(x);
  endfunction
endinterface
"""
        scoreboard = """
module sb;
  initial cov.f_sample(42);
endmodule
"""
        _write(tmp_path / "my_if.sv", cov_if)
        _write(tmp_path / "sb.sv", scoreboard)
        ext = UVMSampleExtractor(
            known_covergroups=["my_cg"],
            known_sample_args=["my_cg.arg.x"],
        )
        result = ext.extract_directory(tmp_path)
        # passes_arg edge for arg0
        passes = [t for t in result.triples if t.predicate == "passes_arg"]
        assert len(passes) == 1
        arg_name = passes[0].object
        # binds_to_arg edge from arg0 -> my_cg.arg.x
        binds = [t for t in result.triples if t.predicate == "binds_to_arg"]
        assert len(binds) == 1
        assert binds[0].subject == arg_name
        assert binds[0].object == "my_cg.arg.x"


# ---------------------------------------------------------------------------
# Cycle 5 — AES end-to-end
# ---------------------------------------------------------------------------


_AES_DV_ROOT = (
    Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "aes" / "dv"
)


@pytest.mark.skipif(
    not (_AES_DV_ROOT / "env" / "aes_scoreboard.sv").exists(),
    reason="OpenTitan AES UVM testbench files not present",
)
class TestCycle5AesEndToEnd:
    AES_COVERGROUPS = [
        "aes_cov_if.aes_aux_regwen_cg",
        "aes_cov_if.aes_ctrl_cg",
        "aes_cov_if.aes_status_cg",
        "aes_cov_if.aes_trigger_cg",
        "aes_cov_if.aes_alert_cg",
        "aes_cov_if.aes_wr_data_interleave_cg",
        "aes_cov_if.aes_rd_data_interleave_cg",
        "aes_cov_if.aes_iv_interleave_cg",
        "aes_cov_if.aes_key_interleave_cg",
        "aes_cov_if.aes_reg_interleave_cg",
        "aes_cov_if.aes_gcm_len_cg",
        "aes_cov_if.aes_ctrl_gcm_reg_cg",
    ]

    def test_aes_end_to_end_audit(self) -> None:
        ext = UVMSampleExtractor(known_covergroups=self.AES_COVERGROUPS)
        # Walk both env and cov directories together so wrappers (defined
        # in cov/aes_cov_if.sv) are known when callsites in env/ are scanned.
        result = ext.extract_directory(
            [_AES_DV_ROOT / "env", _AES_DV_ROOT / "cov"]
        )
        ent_total = result.entities
        tri_total = result.triples
        callsites = [e for e in ent_total if e.type == "UVMSampleCallsite"]
        wrappers = [e for e in ent_total if e.type == "UVMSampleWrapper"]
        samples = [t for t in tri_total if t.predicate == "samples_covergroup"]
        assert len(callsites) >= 10, f"only {len(callsites)} callsites"
        assert len(wrappers) >= 8, f"only {len(wrappers)} wrappers"
        # Every wrapper resolves to a known AES covergroup.
        wraps_edges = [t for t in tri_total if t.predicate == "wraps_covergroup"]
        for t in wraps_edges:
            assert t.object in self.AES_COVERGROUPS, (
                f"wrapper {t.subject} resolved to unknown cg {t.object}"
            )
        # Every known AES covergroup has at least one samples_covergroup edge.
        sampled_cgs = {t.object for t in samples}
        missing = [cg for cg in self.AES_COVERGROUPS if cg not in sampled_cgs]
        assert not missing, f"orphan covergroups: {missing}"
