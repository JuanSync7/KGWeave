# @summary
# TDD guard: sv_connectivity._emit_assertion_edges must resolve clock identifiers
# and referenced signals via pyslang structural AST (spec.clocking + syntax.visit)
# rather than regex-parsing the property's text representation.
#
# iter-013 — replaces _re.findall clock-ident extraction and _IDENT_RE.findall
# signal-ident extraction with structural AST walks.
# @end-summary
"""Structural (non-regex) assertion signal resolution in sv_connectivity.

Ensures that ``_emit_assertion_edges`` uses ``spec.clocking`` and
``syntax.visit()`` rather than ``_re.findall`` / ``_IDENT_RE.findall`` to
identify clock signals and referenced signals in SVA property specs.

RED before iter-013: ``_re.findall(`` is present in the source.
GREEN after iter-013: replaced with structural AST walk.
"""
from __future__ import annotations

import inspect
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("pyslang", reason="pyslang required for SlangHierarchyAnalyzer")


# ---------------------------------------------------------------------------
# Source-level guard — fails until the regex is removed
# ---------------------------------------------------------------------------


def test_assertion_clock_ident_not_via_regex() -> None:
    """``_re.findall`` must not appear in sv_connectivity (clock-ident extraction
    must use ``spec.clocking``, not a regex on the property text string)."""
    from kgweave.knowledge_graph.extraction import sv_connectivity

    src = inspect.getsource(sv_connectivity)
    assert "_re.findall(" not in src, (
        "Clock identifiers in _emit_assertion_edges must be resolved via "
        "spec.clocking (structural AST), not _re.findall on property text."
    )


def test_ident_re_not_used_for_signal_extraction() -> None:
    """``_IDENT_RE`` must not be used to extract signal names from assertion text.
    Signal names must be collected via syntax.visit() on the property syntax node."""
    from kgweave.knowledge_graph.extraction import sv_connectivity

    src = inspect.getsource(sv_connectivity)
    assert "_IDENT_RE.findall(" not in src, (
        "Signal idents in _emit_assertion_edges must be collected via "
        "syntax.visit(), not _IDENT_RE.findall on property text."
    )


# ---------------------------------------------------------------------------
# Behavioural: clock + signal references resolved correctly via AST
# ---------------------------------------------------------------------------

_SV_ASSERTION_REFS = textwrap.dedent(
    """\
    // Adversarial: module keyword followed by a tab (not space), plus a
    // parameterized port declaration, plus a multiline assertion.
    // Old regex-on-text approaches break on the tab and multiline forms.
    module\ttab_sep_mod #(parameter int W = 8) (
        input  logic        clk_i,
        input  logic        rst_ni,
        input  logic [W-1:0] req,
        output logic [W-1:0] ack
    );
        stable_req: assert property (
            @(posedge clk_i) disable iff (!rst_ni)
            req |-> ##1 ack
        );
    endmodule
    """
)


def _run_assertion_refs(tmp_path: Path, src: str, top: str):
    """Compile src, run SlangHierarchyAnalyzer, return triples."""
    from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
    from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

    sv = tmp_path / f"{top}.sv"
    sv.write_text(src)
    fl = tmp_path / "files.f"
    fl.write_text(str(sv) + "\n")

    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(fl),
        backend=backend,
        top_module=top,
    )
    return analyzer.analyze_full()


def test_assertion_references_signal_contains_req_and_ack(tmp_path: Path) -> None:
    """``references_signal`` edges must include both ``req`` and ``ack`` for the
    assertion in *tab_sep_mod*.  This verifies the syntax.visit() identifier walk
    correctly resolves signals even when the module keyword uses a tab separator
    and the assertion spans multiple lines — inputs that the old
    ``_IDENT_RE.findall(expr_text)`` approach handled only accidentally and that
    break structural parsing of the *module* line (but not pyslang elaboration)."""
    result = _run_assertion_refs(tmp_path, _SV_ASSERTION_REFS, "tab_sep_mod")

    ref_objects = {
        t.object
        for t in result.triples
        if t.predicate == "references_signal"
    }
    assert ref_objects, "expected at least one references_signal triple"
    # ``req`` and ``ack`` must both be captured as referenced signals.
    assert any("req" in obj for obj in ref_objects), (
        f"expected req in references_signal targets, got {ref_objects}"
    )
    assert any("ack" in obj for obj in ref_objects), (
        f"expected ack in references_signal targets, got {ref_objects}"
    )


def test_assertion_clock_domain_registered(tmp_path: Path) -> None:
    """``clk_i`` must be registered as a ClockDomain entity — the structural
    ``spec.clocking`` walk must surface it even without the regex ``@(posedge X)``
    text-scan."""
    result = _run_assertion_refs(tmp_path, _SV_ASSERTION_REFS, "tab_sep_mod")

    clock_entity_names = {e.name for e in result.entities if e.type == "ClockDomain"}
    assert "clk_i" in clock_entity_names, (
        f"expected clk_i ClockDomain entity; got {clock_entity_names}"
    )
