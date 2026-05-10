"""Tests for the Phase 1 signal-level dataflow walker (`_emit_dataflow_edges`).

Validates that `reads(lhs_signal, rhs_signal)` triples are emitted from
SystemVerilog continuous and procedural assignments at module scope. Operator
nodes / anonymous temporaries are intentionally NOT materialized — only the
base named persistent signals appear, with the assignment text stored in
``evidence_span``.
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


def _run(tmp_path: Path, src: str, top: str) -> list[Triple]:
    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    fl = _write_filelist(tmp_path, {"top.sv": src})
    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl), backend=backend, top_module=top,
    )
    return analyzer.analyze_full().triples


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


def test_continuous_assign_simple(tmp_path: Path) -> None:
    src = """
    module m(input logic a, output logic y);
      assign y = a;
    endmodule
    """
    triples = _run(tmp_path, src, "m")
    reads = _reads(triples)
    pairs = [(t.subject, t.object) for t in reads]
    assert ("m.y", "m.a") in pairs, f"expected reads(m.y, m.a), got {pairs}"
    edge = next(t for t in reads if (t.subject, t.object) == ("m.y", "m.a"))
    assert edge.evidence_span, "evidence_span should be non-empty"


def test_continuous_assign_multiple_rhs(tmp_path: Path) -> None:
    src = """
    module m(input logic a, input logic b, input logic c, output logic y);
      assign y = a & b | c;
    endmodule
    """
    triples = _run(tmp_path, src, "m")
    reads = _reads(triples)
    pairs = {(t.subject, t.object) for t in reads}
    assert ("m.y", "m.a") in pairs
    assert ("m.y", "m.b") in pairs
    assert ("m.y", "m.c") in pairs
    # All three should share the same evidence_span (same RHS expression).
    spans = {t.evidence_span for t in reads
             if (t.subject, t.object) in
             {("m.y", "m.a"), ("m.y", "m.b"), ("m.y", "m.c")}}
    assert len(spans) == 1, f"expected one shared evidence_span, got {spans}"


def test_always_ff_sequential_read(tmp_path: Path) -> None:
    src = """
    module m(input logic clk, input logic en, input logic d, output logic q);
      logic q_q;
      always_ff @(posedge clk) begin
        if (en) q_q <= d;
      end
      assign q = q_q;
    endmodule
    """
    triples = _run(tmp_path, src, "m")
    reads = _reads(triples)
    pairs = {(t.subject, t.object) for t in reads}
    assert ("m.q_q", "m.d") in pairs, f"missing reads(m.q_q, m.d): {pairs}"
    assert ("m.q_q", "m.en") in pairs, f"missing reads(m.q_q, m.en): {pairs}"
    # Clock must NOT show up as a 'reads' source — it lives on clocked_by.
    for t in reads:
        assert t.object != "m.clk", f"clk should not appear as reads source: {t}"


def test_skip_function_locals(tmp_path: Path) -> None:
    src = """
    module m(input logic [7:0] a, output logic [7:0] y);
      function automatic logic [7:0] inc(input logic [7:0] x);
        logic [7:0] tmp;
        tmp = x + 1;
        return tmp;
      endfunction
      assign y = inc(a);
    endmodule
    """
    triples = _run(tmp_path, src, "m")
    reads = _reads(triples)
    # The function-local 'tmp' and 'x' should NOT appear in any reads edge.
    for t in reads:
        assert "tmp" not in t.subject.split(".")[-1], (
            f"function-local 'tmp' leaked into reads edge: {t}"
        )
        assert "tmp" not in t.object.split(".")[-1], (
            f"function-local 'tmp' leaked into reads edge: {t}"
        )
        # 'x' is a function arg — also must not appear as a module-scope signal.
        assert t.object != "m.x", f"function arg leaked: {t}"
        assert t.subject != "m.x", f"function arg leaked: {t}"


def test_bit_slice_text_in_evidence_span(tmp_path: Path) -> None:
    src = """
    module m(input logic [7:0] a, input logic [7:0] b, output logic [15:0] y);
      assign y[7:0]  = a;
      assign y[15:8] = b;
    endmodule
    """
    triples = _run(tmp_path, src, "m")
    reads = _reads(triples)
    y_a = [t for t in reads if (t.subject, t.object) == ("m.y", "m.a")]
    y_b = [t for t in reads if (t.subject, t.object) == ("m.y", "m.b")]
    assert y_a, "expected reads(m.y, m.a)"
    assert y_b, "expected reads(m.y, m.b)"
    # MultiDiGraph preserves both observations; the per-observation evidence
    # is what carries the slice. We just need each slice to be present in
    # at least one observation across all 'reads' triples.
    all_spans = " || ".join(t.evidence_span for t in reads)
    assert "[7:0]" in all_spans, f"expected '[7:0]' in evidence: {all_spans}"
    assert "[15:8]" in all_spans, f"expected '[15:8]' in evidence: {all_spans}"


def test_skip_parameter_rhs(tmp_path: Path) -> None:
    """Parameters are constants/already-nodes — we skip emitting reads from them.

    Documented choice: a `reads(y, W)` edge would conflate constant binding
    with dataflow. Parameter binding is captured by `binds_parameter`.
    """
    src = """
    module m #(parameter int W = 8) (output logic [7:0] y);
      assign y = W;
    endmodule
    """
    triples = _run(tmp_path, src, "m")
    reads = _reads(triples)
    # No reads edges should target the parameter.
    for t in reads:
        assert t.object != "m.W", f"parameter leaked into reads edge: {t}"
