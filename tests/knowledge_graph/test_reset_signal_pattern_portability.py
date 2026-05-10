"""V3 #7 — portability of reset/clock heuristic in SlangHierarchyAnalyzer.

Default reset regex (rst|reset|por) misses ARM-style ``aresetn`` and other
non-OT reset naming conventions. This test pins:

1. Unit: that the default regex misses ``aresetn`` (motivates the config).
2. Infra: that ``KGConfig.reset_signal_pattern`` exists, round-trips
   through ``from_env``, and threads through ``SlangHierarchyAnalyzer``.
3. Integration: a synthetic non-OT module (``frobnicator_engine`` driven by
   ``aresetn``) elaborates and emits ``reset_by`` edges with the
   custom regex configured, but does *not* with the default regex.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backend import GraphStorageBackend
from kgweave.knowledge_graph.common import KGConfig
from kgweave.knowledge_graph.extraction.sv_connectivity import (
    SlangHierarchyAnalyzer,
    _RESET_NAME_RE,
)


SYNTHETIC_FROBNICATOR = textwrap.dedent(
    """\
    module frobnicator_engine (
        input  logic clk,
        input  logic aresetn,
        input  logic [7:0] data_in,
        output logic [7:0] data_out
    );
        logic [7:0] data_q;
        always_ff @(posedge clk or negedge aresetn) begin
            if (!aresetn) begin
                data_q <= 8'h00;
            end else begin
                data_q <= data_in;
            end
        end
        assign data_out = data_q;
    endmodule
    """
)


def _write_filelist(tmp_path: Path) -> Path:
    sv_path = tmp_path / "frobnicator_engine.sv"
    sv_path.write_text(SYNTHETIC_FROBNICATOR)
    fl = tmp_path / "frob.f"
    fl.write_text(str(sv_path) + "\n")
    return fl


def _make_backend() -> GraphStorageBackend:
    from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
    return NetworkXBackend()


# ---- Unit: default regex misses ARM-style reset ----------------------------


def test_default_reset_regex_misses_aresetn():
    """Default heuristic targets OT-flavored reset names."""
    assert _RESET_NAME_RE.search("rst_n")
    assert _RESET_NAME_RE.search("por_n")
    # ARM AXI: aresetn / nrst -- not matched by the default OT regex.
    assert _RESET_NAME_RE.search("aresetn") is None


# ---- Infra: KGConfig field round-trips ------------------------------------


def test_kgconfig_reset_signal_pattern_default_is_none_or_ot():
    """Default config must not break OT behavior."""
    cfg = KGConfig()
    # Either unset (None — code falls back to internal default) or matches
    # the OT default. Either way OT codebases keep working.
    assert getattr(cfg, "reset_signal_pattern", None) in (None, "", _RESET_NAME_RE.pattern)


def test_kgconfig_reset_signal_pattern_settable():
    cfg = KGConfig(reset_signal_pattern=r"(^|_)(rst|reset|por|aresetn|nrst)(_|$)")
    assert "aresetn" in cfg.reset_signal_pattern


def test_kgconfig_reset_signal_pattern_from_env():
    pat = r"(^|_)(rst|reset|por|aresetn|nrst)(_|$)"
    cfg = KGConfig.from_env({"RAG_KG_RESET_SIGNAL_PATTERN": pat})
    assert cfg.reset_signal_pattern == pat


# ---- Integration: non-OT codebase emits reset_by with config --------------


def test_synthetic_aresetn_module_default_regex_misses_reset(tmp_path):
    """Demonstrate the OT-ism: default config produces no reset_by edge for
    ``aresetn`` even though it elaborates fine."""
    fl = _write_filelist(tmp_path)
    backend = _make_backend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl),
        backend=backend,
        top_module="frobnicator_engine",
    )
    triples = analyzer.analyze()
    reset_edges = [t for t in triples if t.predicate == "reset_by"]
    # Default regex misses aresetn → no reset_by edge.
    assert reset_edges == [], (
        f"Expected no reset_by edges with default regex, got: {reset_edges}"
    )
    # The clock_by edge should still be emitted for the real clock; the
    # signal is simply (mis)classified.
    clocked_edges = [t for t in triples if t.predicate == "clocked_by"]
    # With default OT regex aresetn falls through and is treated as a clock.
    clocked_signals = {t.object for t in clocked_edges}
    assert "clk" in clocked_signals


def test_synthetic_aresetn_module_with_config_emits_reset_by(tmp_path):
    """When the user configures an aresetn-aware pattern the resetn signal
    is correctly tagged as a ResetDomain rather than a ClockDomain."""
    fl = _write_filelist(tmp_path)
    backend = _make_backend()
    custom = r"(^|_)(rst|reset|por|aresetn|nrst|sresetn)(_|$)|^aresetn$|^nrst$"
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl),
        backend=backend,
        top_module="frobnicator_engine",
        reset_signal_pattern=custom,
    )
    triples = analyzer.analyze()
    reset_edges = [t for t in triples if t.predicate == "reset_by"]
    reset_signals = {t.object for t in reset_edges}
    assert "aresetn" in reset_signals, (
        f"Expected aresetn → reset_by, got: {reset_edges}"
    )
    # And the clock should not have aresetn confused as a clock anymore.
    clocked_edges = [t for t in triples if t.predicate == "clocked_by"]
    clocked_signals = {t.object for t in clocked_edges}
    assert "clk" in clocked_signals
    assert "aresetn" not in clocked_signals
