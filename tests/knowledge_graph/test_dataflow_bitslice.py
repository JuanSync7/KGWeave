"""Tests for Phase-1 bit-slice refinement on dataflow ``reads`` edges.

Promotes the symbolic LHS / RHS slice text out of ``evidence_span`` into
structured ``lhs_slice`` / ``rhs_slice`` attributes on each ``Triple`` and
on the corresponding edge in the NetworkX backend. These slices are kept
**symbolic** — parameter expressions are preserved as raw text and not
resolved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.common import Triple
from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _write_filelist(tmp_path: Path, files: dict[str, str]) -> Path:
    paths = []
    for name, content in files.items():
        p = tmp_path / name
        p.write_text(content)
        paths.append(p.name)
    fl = tmp_path / "files.f"
    fl.write_text("\n".join(paths) + "\n")
    return fl


def _reads(triples: list[Triple]) -> list[Triple]:
    return [t for t in triples if t.predicate == "reads"]


def _run(tmp_path: Path, src: str, top: str):
    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    fl = _write_filelist(tmp_path, {"top.sv": src})
    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl), backend=backend, top_module=top,
    )
    result = analyzer.analyze_full()
    return result.triples, backend


def _find_reads(triples, subj, obj):
    return [
        t for t in _reads(triples)
        if t.subject == subj and t.object == obj
    ]


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


def test_lhs_slice_captured(tmp_path: Path) -> None:
    src = """
    module m(input logic [7:0] a, output logic [31:0] data_o);
      assign data_o[31:24] = a;
    endmodule
    """
    triples, _ = _run(tmp_path, src, "m")
    edges = _find_reads(triples, "m.data_o", "m.a")
    assert edges, "expected reads(m.data_o, m.a)"
    t = edges[0]
    assert t.lhs_slice == "[31:24]", f"got {t.lhs_slice!r}"
    assert t.rhs_slice is None, f"got {t.rhs_slice!r}"


def test_rhs_slice_captured(tmp_path: Path) -> None:
    src = """
    module m(input logic [31:0] bus, output logic [7:0] x);
      assign x = bus[7:0];
    endmodule
    """
    triples, _ = _run(tmp_path, src, "m")
    edges = _find_reads(triples, "m.x", "m.bus")
    assert edges
    t = edges[0]
    assert t.lhs_slice is None
    assert t.rhs_slice == "[7:0]", f"got {t.rhs_slice!r}"


def test_both_sides_slice(tmp_path: Path) -> None:
    src = """
    module m(input logic [31:0] bus, output logic [31:0] data_o);
      assign data_o[7:0] = bus[15:8];
    endmodule
    """
    triples, _ = _run(tmp_path, src, "m")
    edges = _find_reads(triples, "m.data_o", "m.bus")
    assert edges
    t = edges[0]
    assert t.lhs_slice == "[7:0]"
    assert t.rhs_slice == "[15:8]"


def test_single_bit_select(tmp_path: Path) -> None:
    src = """
    module m(input logic [31:0] ctrl, output logic flag);
      assign flag = ctrl[5];
    endmodule
    """
    triples, _ = _run(tmp_path, src, "m")
    edges = _find_reads(triples, "m.flag", "m.ctrl")
    assert edges
    t = edges[0]
    assert t.lhs_slice is None
    assert t.rhs_slice == "[5]", f"got {t.rhs_slice!r}"


def test_symbolic_slice_preserved(tmp_path: Path) -> None:
    src = """
    module m #(parameter int ADDR_W = 8) (
        input logic [31:0] src,
        output logic [31:0] data_o
    );
      assign data_o[ADDR_W-1:0] = src[ADDR_W-1:0];
    endmodule
    """
    triples, _ = _run(tmp_path, src, "m")
    edges = _find_reads(triples, "m.data_o", "m.src")
    assert edges
    t = edges[0]
    assert t.lhs_slice == "[ADDR_W-1:0]", f"got {t.lhs_slice!r}"
    assert t.rhs_slice == "[ADDR_W-1:0]", f"got {t.rhs_slice!r}"


def test_no_slice_yields_none(tmp_path: Path) -> None:
    src = """
    module m(input logic a, output logic y);
      assign y = a;
    endmodule
    """
    triples, _ = _run(tmp_path, src, "m")
    edges = _find_reads(triples, "m.y", "m.a")
    assert edges
    t = edges[0]
    assert t.lhs_slice is None
    assert t.rhs_slice is None


def test_mixed_slices_top_level_none_per_evidence_set(tmp_path: Path) -> None:
    """Two assignments with the same (s,p,o) but differing slices merge into
    one edge whose top-level slice attrs go to ``None`` (mixed), with the
    per-observation slice tuples retained on the ``evidences`` list."""
    src = """
    module m(input logic [7:0] a, output logic [7:0] data_o);
      assign data_o = a;
      assign data_o[7:0] = a[7:0];
    endmodule
    """
    triples, backend = _run(tmp_path, src, "m")
    backend.upsert_triples([t for t in triples if t.predicate == "reads"])

    g = backend.graph
    assert g.has_edge("m.data_o", "m.a", key="reads")
    edge = g["m.data_o"]["m.a"]["reads"]

    # Top-level slice attrs collapse to None when observations disagree.
    assert edge.get("lhs_slice") is None, edge.get("lhs_slice")
    assert edge.get("rhs_slice") is None, edge.get("rhs_slice")

    # Per-observation slice info is preserved on the evidences list.
    evidences = edge.get("evidences", [])
    assert len(evidences) >= 2, f"expected >=2 evidences, got {evidences}"
    slice_pairs = {
        (ev.get("lhs_slice"), ev.get("rhs_slice")) for ev in evidences
    }
    assert (None, None) in slice_pairs, slice_pairs
    assert ("[7:0]", "[7:0]") in slice_pairs, slice_pairs
