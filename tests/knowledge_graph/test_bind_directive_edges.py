# @summary
# TDD: SlangHierarchyAnalyzer must emit `bound_into` edges from SystemVerilog
# `bind` directives. Each directive of the form
#   bind <target_mod> <bound_def> u_inst(...);
# produces one triple `subject=<bound_def>, predicate=bound_into, object=<target_mod>`
# regardless of whether <bound_def> resolves to a known module/interface
# (unresolvable references are an audit signal, not an error).
# @end-summary
"""Tests for `bound_into` edges emitted from SystemVerilog bind directives."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


_AES_DV_BIND_DIR = (
    Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "aes" / "dv"
)
_AES_RTL_DIR = (
    Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "aes" / "rtl"
)
_AES_COV_DIR = _AES_DV_BIND_DIR / "cov"
_AES_SVA_DIR = _AES_DV_BIND_DIR / "sva"
_PRIM_RTL_DIR = (
    Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "prim" / "rtl"
)


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


def _bound_into_pairs(result) -> list[tuple[str, str]]:
    return [
        (t.subject, t.object)
        for t in result.triples
        if t.predicate == "bound_into"
    ]


def test_minimal_bind_emits_bound_into(tmp_path: Path) -> None:
    """`bind a b u_b()` → one triple `b -> bound_into -> a`."""
    sv = """\
module a; endmodule
module b; endmodule
bind a b u_b();
"""
    fl = _build_filelist(tmp_path, [("d.sv", sv)])
    result = _run(fl)
    pairs = _bound_into_pairs(result)
    assert ("b", "a") in pairs, (
        f"expected (b, a) bound_into pair; got: {pairs}"
    )
    # Exactly one such triple — no duplicate emission across instance walks.
    assert pairs.count(("b", "a")) == 1, (
        f"expected exactly one (b, a) bound_into edge; got: {pairs}"
    )


def test_bind_into_interface_emits_bound_into(tmp_path: Path) -> None:
    """`bind a my_if u_iff(.clk)` — bind source may be an interface."""
    sv = """\
module a(input bit clk); endmodule
interface my_if(input bit clk); endinterface
bind a my_if u_iff(.clk(clk));
"""
    fl = _build_filelist(tmp_path, [("d.sv", sv)])
    result = _run(fl)
    pairs = _bound_into_pairs(result)
    assert ("my_if", "a") in pairs, (
        f"expected (my_if, a) bound_into pair; got: {pairs}"
    )


def test_bind_unresolvable_source_still_emits(tmp_path: Path) -> None:
    """Bind source that doesn't resolve to a known module/interface is an
    audit signal — the edge MUST still be emitted with the bare name."""
    sv = """\
module a; endmodule
bind a does_not_exist u_inst();
"""
    fl = _build_filelist(tmp_path, [("d.sv", sv)])
    result = _run(fl)
    pairs = _bound_into_pairs(result)
    assert ("does_not_exist", "a") in pairs, (
        f"expected (does_not_exist, a) bound_into pair; got: {pairs}"
    )


def test_aes_dataset_emits_bound_into_edges(tmp_path: Path) -> None:
    """End-to-end: real OpenTitan AES bind files emit ≥4 bound_into edges
    targeting `aes`. Skipped when the dataset is absent."""
    if not _AES_RTL_DIR.exists() or not _AES_COV_DIR.exists() or not _AES_SVA_DIR.exists():
        pytest.skip("OpenTitan AES dataset not present")

    rtl_files = sorted(_AES_RTL_DIR.glob("*.sv"))
    cov_files = sorted(_AES_COV_DIR.glob("*.sv"))
    sva_files = sorted(_AES_SVA_DIR.glob("*.sv"))
    if not (rtl_files and cov_files and sva_files):
        pytest.skip("AES rtl/cov/sva files missing")

    fl = tmp_path / "all.f"
    fl.write_text("\n".join(str(p) for p in rtl_files + cov_files + sva_files) + "\n")

    incdirs = [str(_PRIM_RTL_DIR)] if _PRIM_RTL_DIR.exists() else []
    result = _run(
        fl,
        top="aes",
        incdirs=incdirs,
        defines=["INC_ASSERT", "FPV_ON", "SIMULATION", "EN_MASKING"],
    )
    pairs = _bound_into_pairs(result)
    targeting_aes = [p for p in pairs if p[1] == "aes"]
    assert len(targeting_aes) >= 4, (
        f"expected ≥4 bound_into edges targeting 'aes'; got {len(targeting_aes)}: "
        f"{targeting_aes}"
    )
