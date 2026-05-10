# @summary
# TDD: relax coverpoint `observes` filter to include FormalArgument symbols
# from `with function sample(...)` covergroups, emitting Covergroup_SampleArg
# entities and `has_sample_arg` composition edges.
# Cycles:
#   1 — observes edge targets Covergroup_SampleArg for function-argument coverpoints
#   2 — has_sample_arg composition edge + AES end-to-end (if fixture present)
#   + regression guard for the original module-scope observes path
# @end-summary
"""Tests for sample-function argument observes/has_sample_arg extraction."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


def _run(tmp_path: Path, src: str, top: str = "i"):
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


# Minimal module with a `with function sample` covergroup.
# Using a module (not a bare interface) because pyslang surfaces interfaces
# as root-level SymbolKind.Instance nodes that are NOT in topInstances
# unless instantiated by a module in the same compilation — so a bare
# interface never enters the _walk_instance path on its own.
_IF_SAMPLE_ARG = """\
module i;
  covergroup cg with function sample(bit x);
    cp_x: coverpoint x;
  endgroup
  cg cg_inst;
endmodule
"""

# Minimal module where coverpoint observes a module-scope port (original path).
_MOD_MODULE_SCOPE = """\
module dut(input logic clk, input logic [1:0] mode);
  covergroup my_cg @(posedge clk);
    cp_mode: coverpoint mode;
  endgroup
endmodule
"""


class TestFunctionArgObserves:
    """Cycle 1: observes edge from coverpoint to Covergroup_SampleArg."""

    def test_sample_arg_entity_emitted(self, tmp_path: Path) -> None:
        result = _run(tmp_path, _IF_SAMPLE_ARG)
        args = [e for e in result.entities
                if e.type == "Covergroup_SampleArg"]
        assert len(args) == 1, [(e.name, e.type) for e in result.entities]
        assert args[0].name == "i.cg.arg.x"

    def test_observes_edge_to_sample_arg(self, tmp_path: Path) -> None:
        result = _run(tmp_path, _IF_SAMPLE_ARG)
        obs = [t for t in result.triples if t.predicate == "observes"]
        assert len(obs) == 1, obs
        assert obs[0].subject == "i.cg.cp_x"
        assert obs[0].object == "i.cg.arg.x"


class TestHasSampleArgComposition:
    """Cycle 2: has_sample_arg composition edge from covergroup to SampleArg."""

    def test_has_sample_arg_edge(self, tmp_path: Path) -> None:
        result = _run(tmp_path, _IF_SAMPLE_ARG)
        edges = [t for t in result.triples if t.predicate == "has_sample_arg"]
        assert len(edges) == 1, edges
        assert edges[0].subject == "i.cg"
        assert edges[0].object == "i.cg.arg.x"

    def test_has_sample_arg_emitted_once_per_arg(self, tmp_path: Path) -> None:
        """Two coverpoints sampling the same arg must produce only one
        has_sample_arg edge and one SampleArg entity (dedup on first emit)."""
        src = """\
module i;
  covergroup cg with function sample(bit x);
    cp_x1: coverpoint x;
    cp_x2: coverpoint x;
  endgroup
  cg cg_inst;
endmodule
"""
        result = _run(tmp_path, src)
        args = [e for e in result.entities if e.type == "Covergroup_SampleArg"]
        assert len(args) == 1
        edges = [t for t in result.triples if t.predicate == "has_sample_arg"]
        assert len(edges) == 1
        obs = [t for t in result.triples if t.predicate == "observes"]
        assert len(obs) == 2

    @pytest.mark.skipif(
        not Path(os.environ.get(
            "KGWEAVE_OPENTITAN_ROOT",
            str(Path.home() / "RagWeave" / "opentitan_data"),
        )).joinpath("hw", "ip", "aes", "dv", "cov", "aes_cov_if.sv").exists(),
        reason="AES dv/cov fixture not present",
    )
    def test_aes_cov_if_end_to_end(self, tmp_path: Path) -> None:
        """End-to-end: aes_cov_if.sv must produce >=20 observes edges
        and >=20 Covergroup_SampleArg entities.  The file has 37 coverpoints
        across 12 covergroups; coverpoints that sample ternary/concat
        expressions are silently skipped in Phase 1.  The lower bound
        of 20 gives headroom for different elaboration views while still
        proving the main path fires on real AES data."""
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        ot_root = Path(os.environ.get(
            "KGWEAVE_OPENTITAN_ROOT",
            str(Path.home() / "RagWeave" / "opentitan_data"),
        ))
        cov_if = ot_root / "hw" / "ip" / "aes" / "dv" / "cov" / "aes_cov_if.sv"
        sv_stubs = Path(__file__).resolve().parents[2] / "data" / "sv_stubs"
        stub_files = sorted(sv_stubs.glob("*.sv")) if sv_stubs.exists() else []

        all_files = stub_files + [cov_if]
        fl = tmp_path / "aes_cov.f"
        fl.write_text("\n".join(str(p) for p in all_files) + "\n")

        dv_utils = ot_root / "hw" / "dv" / "sv" / "dv_utils"
        prim_rtl = ot_root / "hw" / "ip" / "prim" / "rtl"
        incdirs = [str(d) for d in [dv_utils, prim_rtl] if d.exists()]

        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl),
            backend=backend,
            top_module="aes_cov_if",
            incdirs=incdirs or None,
            defines=["INC_ASSERT", "FPV_ON", "SIMULATION", "EN_MASKING"],
        )
        result = analyzer.analyze_full()

        n_obs = sum(1 for t in result.triples if t.predicate == "observes")
        n_arg = sum(1 for e in result.entities
                    if e.type == "Covergroup_SampleArg")
        n_has_arg = sum(1 for t in result.triples
                        if t.predicate == "has_sample_arg")

        assert n_obs >= 20, (
            f"Expected >=20 observes edges from aes_cov_if, got {n_obs}"
        )
        assert n_arg >= 20, (
            f"Expected >=20 Covergroup_SampleArg entities, got {n_arg}"
        )
        assert n_has_arg >= 1, (
            f"Expected >=1 has_sample_arg edges, got {n_has_arg}"
        )


class TestModuleScopeObservesRegression:
    """Verify the original module-scope signal observes path still works."""

    def test_module_scope_observes_still_works(self, tmp_path: Path) -> None:
        result = _run(tmp_path, _MOD_MODULE_SCOPE, top="dut")
        obs = [t for t in result.triples if t.predicate == "observes"]
        assert len(obs) == 1, obs
        # Original naming: {module}.{signal} — NOT a SampleArg node.
        assert obs[0].subject == "dut.my_cg.cp_mode"
        assert obs[0].object == "dut.mode"
        # No SampleArg entities must exist in the module-scope case.
        args = [e for e in result.entities
                if e.type == "Covergroup_SampleArg"]
        assert args == [], args
