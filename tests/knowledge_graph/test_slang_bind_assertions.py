# @summary
# TDD: SlangHierarchyAnalyzer must surface bind-attached SVA assertions.
# A `bind target_mod checker_mod u_inst(...)` directive causes slang to
# inject `u_inst` as a child instance of every elaborated `target_mod`
# instance. This module verifies: (a) the bound Instance entity appears,
# (b) assertions inside the checker are emitted as SVA_Assertion entities,
# (c) has_assertion edges anchor to the checker module definition, and
# (d) real OpenTitan AES dv/sva files add ≥1 assertion beyond the RTL
# baseline (skipped when data is absent).
# @end-summary
"""Tests for bind-attached SVA assertion discovery in SlangHierarchyAnalyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


_AES_SVA_DIR = (
    Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "aes" / "dv" / "sva"
)
_AES_RTL_DIR = (
    Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "aes" / "rtl"
)
_PRIM_RTL_DIR = (
    Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "prim" / "rtl"
)


TARGET_SV = """\
module target_mod(
    input logic clk_i,
    input logic rst_ni,
    input logic a_i
);
endmodule

module top_wrapper(
    input logic clk_i,
    input logic rst_ni,
    input logic a_i
);
  target_mod u_target(.clk_i, .rst_ni, .a_i);
endmodule
"""

CHECKER_SV = """\
module aes_assertions(
    input logic clk_i,
    input logic rst_ni,
    input logic a_i
);
  MyCheck_A: assert property (
    @(posedge clk_i) disable iff (!rst_ni) a_i
  );
endmodule

bind target_mod aes_assertions u_chk(.clk_i, .rst_ni, .a_i);
"""


def _build_filelist(tmp_path: Path, files: list[tuple[str, str]]) -> Path:
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files:
        (src_dir / name).write_text(text)
    fl = tmp_path / "files.f"
    fl.write_text("\n".join(str(src_dir / name) for name, _ in files) + "\n")
    return fl


def _run(filelist: Path, top: str = "", **kw):
    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(filelist),
        backend=backend,
        top_module=top,
        **kw,
    )
    return analyzer.analyze_full()


def test_bind_directive_creates_instance(tmp_path: Path) -> None:
    """A `bind target_mod checker u_chk(...)` must produce an Instance of checker
    bound into target_mod.  The `instance_of` edge `aes_assertions` must appear."""
    fl = _build_filelist(
        tmp_path,
        [("target.sv", TARGET_SV), ("checker.sv", CHECKER_SV)],
    )
    result = _run(fl, top="top_wrapper")

    instance_of_triples = [
        t for t in result.triples if t.predicate == "instance_of"
    ]
    bound_instance_triples = [
        t for t in instance_of_triples if t.object == "aes_assertions"
    ]
    assert bound_instance_triples, (
        f"expected at least one instance_of 'aes_assertions' triple; "
        f"got instance_of objects: {[t.object for t in instance_of_triples]}"
    )


def test_bind_assertion_extracted(tmp_path: Path) -> None:
    """Assertions inside a checker module bound via `bind` must surface as
    SVA_Assertion entities."""
    fl = _build_filelist(
        tmp_path,
        [("target.sv", TARGET_SV), ("checker.sv", CHECKER_SV)],
    )
    result = _run(fl, top="top_wrapper")

    sva_names = [e.name for e in result.entities if e.type == "SVA_Assertion"]
    assert any("MyCheck_A" in n for n in sva_names), (
        f"expected SVA_Assertion containing 'MyCheck_A'; got: {sva_names}"
    )


def test_bind_target_resolves_module(tmp_path: Path) -> None:
    """The has_assertion edge must be anchored to the checker module definition
    (aes_assertions), not the bind target (target_mod).

    The SlangHierarchyAnalyzer emits `has_assertion` from the module definition
    that directly contains the ProceduralBlock — i.e. the checker definition —
    not from the bind-target definition.  This is consistent with RTL assertions:
    `has_assertion` always points from the owning module def to its assertion.
    """
    fl = _build_filelist(
        tmp_path,
        [("target.sv", TARGET_SV), ("checker.sv", CHECKER_SV)],
    )
    result = _run(fl, top="top_wrapper")

    has_assert_triples = [
        t for t in result.triples if t.predicate == "has_assertion"
    ]
    checker_has_assert = [
        t for t in has_assert_triples if t.subject == "aes_assertions"
    ]
    assert checker_has_assert, (
        f"expected has_assertion edge from 'aes_assertions'; "
        f"got subjects: {[t.subject for t in has_assert_triples]}"
    )
    assert any("MyCheck_A" in t.object for t in checker_has_assert), (
        f"expected object containing 'MyCheck_A'; "
        f"got objects: {[t.object for t in checker_has_assert]}"
    )


def test_real_aes_dv_sva_smoke(tmp_path: Path) -> None:
    """Adding dv/sva/*.sv to the AES filelist must increase the SVA count beyond
    the RTL-only baseline of 41.  Skipped when opentitan data is absent."""
    if not _AES_SVA_DIR.exists():
        pytest.skip(f"OpenTitan AES dv/sva not found at {_AES_SVA_DIR}")
    if not _AES_RTL_DIR.exists():
        pytest.skip(f"OpenTitan AES rtl not found at {_AES_RTL_DIR}")

    prim_incdir = [str(_PRIM_RTL_DIR)] if _PRIM_RTL_DIR.exists() else []

    rtl_files = sorted(_AES_RTL_DIR.glob("*.sv"))
    rtl_fl = tmp_path / "rtl.f"
    rtl_fl.write_text("\n".join(str(p) for p in rtl_files) + "\n")

    backend_rtl = NetworkXBackend()
    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    rtl_result = SlangHierarchyAnalyzer(
        filelist_path=str(rtl_fl),
        backend=backend_rtl,
        top_module="aes",
        incdirs=prim_incdir,
        defines=["INC_ASSERT", "FPV_ON", "SIMULATION"],
    ).analyze_full()
    rtl_sva_count = sum(1 for e in rtl_result.entities if e.type == "SVA_Assertion")

    sva_files = [f for f in sorted(_AES_SVA_DIR.glob("*.sv"))]
    all_fl = tmp_path / "all.f"
    all_fl.write_text(
        "\n".join(str(p) for p in rtl_files + sva_files) + "\n"
    )

    backend_all = NetworkXBackend()
    all_result = SlangHierarchyAnalyzer(
        filelist_path=str(all_fl),
        backend=backend_all,
        top_module="aes",
        incdirs=prim_incdir,
        defines=["INC_ASSERT", "FPV_ON", "SIMULATION", "EN_MASKING"],
    ).analyze_full()
    all_sva_count = sum(1 for e in all_result.entities if e.type == "SVA_Assertion")

    assert all_sva_count > rtl_sva_count, (
        f"expected SVA count to increase after adding dv/sva files; "
        f"RTL-only: {rtl_sva_count}, with SVA: {all_sva_count}"
    )
    bind_sva_names = [
        e.name for e in all_result.entities
        if e.type == "SVA_Assertion" and e.name not in {
            f.name for f in rtl_result.entities if f.type == "SVA_Assertion"
        }
    ]
    assert bind_sva_names, "expected at least one new SVA_Assertion from bind SVA files"
