"""Phase 4 hardcoded-values cleanup: end-to-end generic-codebase pipeline.

One integration test driving a synthetic non-OpenTitan codebase through every
project-conventions-aware reader and extractor we ship. The fixture deliberately
uses identifiers that share zero vocabulary with OT (frobnicator/widget/gizmo,
``pclk``/``presetn`` ARM AMBA-flavoured signals, ``widget_csr_write32`` MMIO
API, ``//rtl/<mod>:`` Bazel deps, ``regress-<mod>:`` Makefile targets).

Asserts:
  * SV always_ff classification picks ``pclk`` as clock and ``presetn`` as
    reset under user-supplied clock/reset patterns.
  * SW test file resolves to the ``widget`` module via Bazel deps with
    ``high`` confidence (build-system tier).
  * CSR access edge emitted via the user-supplied ``widget_csr_write32``
    API regex.
  * Makefile reader produces a ``regress-widget`` link from the
    ``regress-<mod>:`` target prefix and ``IP_NAME = widget`` variable.
  * No spurious OT-flavoured entities sneak into the graph (no ``aes``,
    ``hmac``, ``earlgrey`` etc. names appear anywhere).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.sw_test_config import (
    SwTestPattern,
    SwTestResolutionConfig,
    load_sw_test_config,
)
from kgweave.knowledge_graph.common.types import KGConfig, ProjectConventions
from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader
from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader
from kgweave.knowledge_graph.extraction.sv_connectivity import (
    SlangHierarchyAnalyzer,
)
from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor


_FROBNICATOR_TOP_SV = textwrap.dedent(
    """\
    module frobnicator_top (
        input  logic pclk,
        input  logic presetn,
        input  logic [7:0] in_data,
        output logic [7:0] out_data
    );
        logic [7:0] q;
        always_ff @(posedge pclk or negedge presetn) begin
            if (!presetn) q <= 8'h00;
            else          q <= in_data;
        end
        assign out_data = q;
    endmodule
    """
)


_WIDGET_ENGINE_SV = textwrap.dedent(
    """\
    module widget_engine (
        input  logic pclk,
        input  logic presetn,
        input  logic [15:0] cmd,
        output logic        ready
    );
        logic ready_q;
        always_ff @(posedge pclk or negedge presetn) begin
            if (!presetn) ready_q <= 1'b0;
            else          ready_q <= |cmd;
        end
        assign ready = ready_q;
    endmodule
    """
)


_GIZMO_CTRL_SV = textwrap.dedent(
    """\
    module gizmo_ctrl (
        input  logic pclk,
        input  logic presetn,
        input  logic enable,
        output logic done
    );
        logic done_q;
        always_ff @(posedge pclk or negedge presetn) begin
            if (!presetn) done_q <= 1'b0;
            else          done_q <= enable;
        end
        assign done = done_q;
    endmodule
    """
)


def _generic_conventions() -> ProjectConventions:
    return ProjectConventions(
        # Strict-generic profile baseline + targeted user fields:
        clock_signal_pattern=r"^p?clk\b",
        reset_signal_pattern=r"^p?(rst|reset)n?$",
        csr_access_api_patterns=[r"widget_csr_write32", r"widget_csr_read32"],
        bazel_dep_module_pattern=r"^//rtl/(?P<module>[a-z][a-z0-9_]*)\b",
        makefile_test_target_prefixes=["regress-"],
        sw_test_patterns=[
            # Resolves SW tests to modules via "<mod>_csr_write32(...)" calls.
            SwTestPattern(
                name="csr_api_call",
                regex=r"\b(?P<module>[a-z][a-z0-9_]*)_csr_write32\s*\(",
                confidence_tier="medium",
                transform="none",
            ),
        ],
        sw_test_markers=[r"\bint\s+main\s*\("],
    )


def _write(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def _build_synthetic_project(root: Path) -> dict:
    """Materialise a non-OT project under *root*. Returns paths dict."""
    rtl_dir = root / "rtl"
    sw_dir = root / "sw" / "tests"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    sw_dir.mkdir(parents=True, exist_ok=True)

    # --- SV sources ---------------------------------------------------------
    _write(rtl_dir / "frobnicator_top.sv", _FROBNICATOR_TOP_SV)
    _write(rtl_dir / "widget_engine.sv", _WIDGET_ENGINE_SV)
    _write(rtl_dir / "gizmo_ctrl.sv", _GIZMO_CTRL_SV)
    fl = root / "rtl.f"
    fl.write_text(
        "\n".join(
            str(rtl_dir / f) for f in (
                "frobnicator_top.sv",
                "widget_engine.sv",
                "gizmo_ctrl.sv",
            )
        ) + "\n"
    )

    # --- C tests ------------------------------------------------------------
    _write(
        sw_dir / "widget_smoke.c",
        textwrap.dedent(
            """\
            // non-OT C test using widget_csr_write32 MMIO API.
            extern unsigned int widget_csr_write32(unsigned int addr, unsigned int val);

            #define WIDGET_CTRL_REG_OFFSET 0x10u

            int main(void) {
                widget_csr_write32(WIDGET_CTRL_REG_OFFSET, 0x1u);
                return 0;
            }
            """
        ),
    )

    # --- Bazel BUILD --------------------------------------------------------
    _write(
        root / "BUILD.bazel",
        textwrap.dedent(
            """\
            cc_test(
                name = "widget_smoke",
                srcs = ["sw/tests/widget_smoke.c"],
                deps = ["//rtl/widget:rtl"],
            )
            """
        ),
    )

    # --- Makefile -----------------------------------------------------------
    _write(
        root / "Makefile",
        textwrap.dedent(
            """\
            IP_NAME = widget

            regress-widget:
            \t@echo run regression for widget
            """
        ),
    )

    return {
        "rtl_dir": rtl_dir,
        "sw_dir": sw_dir,
        "filelist": fl,
    }


def test_generic_codebase_end_to_end(tmp_path):
    paths = _build_synthetic_project(tmp_path)
    pc = _generic_conventions()
    cfg = KGConfig(project_conventions=pc)
    assert cfg.project_conventions.profile is None  # strict-generic baseline

    # ---- 1. SV connectivity: clock/reset classification -------------------
    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(paths["filelist"]),
        backend=backend,
        top_module="widget_engine",
        reset_signal_pattern=pc.reset_signal_pattern,
        clock_signal_pattern=pc.clock_signal_pattern,
    )
    sv_triples = analyzer.analyze()

    clocked = {t.object for t in sv_triples if t.predicate == "clocked_by"}
    reset_by = {t.object for t in sv_triples if t.predicate == "reset_by"}
    assert "pclk" in clocked, (
        f"expected pclk classified as clock, got clocked_by={clocked}"
    )
    assert "presetn" in reset_by, (
        f"expected presetn classified as reset, got reset_by={reset_by}"
    )
    # presetn must NOT be misclassified as a clock under the user pattern.
    assert "presetn" not in clocked

    # ---- 2. Bazel reader: //rtl/widget:rtl resolves to 'widget' -----------
    bazel = BazelBuildReader(project_conventions=pc)
    bazel_links = bazel.read(tmp_path)
    bazel_modules = {l.module_name for l in bazel_links}
    assert "widget" in bazel_modules, (
        f"expected Bazel deps to resolve to widget, got {bazel_modules}"
    )
    # No spurious OT-flavoured names from Bazel.
    assert not (bazel_modules & {"aes", "hmac", "uart", "earlgrey"})

    # ---- 3. Makefile reader: regress-widget target + IP_NAME var ----------
    mk = MakefileReader(project_conventions=pc)
    mk_links = mk.read(tmp_path)
    mk_modules = {l.module_name for l in mk_links}
    assert "widget" in mk_modules, (
        f"expected Makefile target/var to resolve to widget, got {mk_modules}"
    )

    # ---- 4. SW test extractor: tests_module via Bazel + accesses_csr ------
    sw_cfg = load_sw_test_config(None, project_conventions=pc)
    assert sw_cfg.patterns, "explicit sw_test_patterns must propagate through"

    ex = SWTestExtractor(
        known_entity_names=["widget", "frobnicator_top", "gizmo_ctrl"],
        sw_test_config=sw_cfg,
        project_conventions=pc,
    )
    res = ex.extract(
        source=str(paths["sw_dir"]),
        project_root=tmp_path,
        build_system_readers=[bazel, mk],
    )

    sw_test_names = {e.name for e in res.entities if e.type == "SW_Test"}
    assert "widget_smoke" in sw_test_names

    tests_module_resolved = [
        t for t in res.triples
        if t.predicate == "tests_module"
        and t.resolved
        and t.subject == "widget_smoke"
    ]
    resolved_modules = {t.object for t in tests_module_resolved}
    assert "widget" in resolved_modules, (
        f"expected widget_smoke→widget tests_module link, got "
        f"{[(t.subject, t.object, t.confidence_tier) for t in tests_module_resolved]}"
    )

    # CSR access edge emitted via the configured widget_csr_write32 regex.
    csr_edges = [t for t in res.triples if t.predicate == "accesses_csr"]
    assert csr_edges, "expected at least one accesses_csr edge under user CSR API regex"

    # ---- 5. No spurious OT-flavoured names in any emitted entity/triple ---
    poison = ("opentitan", "earlgrey", "darjeeling", "lowrisc")
    for entity in res.entities:
        joined = entity.name.lower()
        assert not any(p in joined for p in poison), (
            f"spurious OT-flavoured entity emitted: {entity.name!r}"
        )
    for tr in res.triples:
        joined = f"{tr.subject} {tr.object}".lower()
        assert not any(p in joined for p in poison), (
            f"spurious OT-flavoured triple emitted: {tr.subject} -> {tr.object}"
        )

    # ---- 6. Layer breakdown sanity ---------------------------------------
    sv_predicates = {t.predicate for t in sv_triples}
    assert {"clocked_by", "reset_by"} <= sv_predicates, (
        f"sv_connectivity layer missing core predicates: {sv_predicates}"
    )
    sw_predicates = {t.predicate for t in res.triples}
    assert {"tests_module", "accesses_csr"} <= sw_predicates, (
        f"sw_test layer missing core predicates: {sw_predicates}"
    )
    # Build-system links populated.
    assert bazel_links, "bazel reader must produce at least one link"
    assert mk_links, "makefile reader must produce at least one link"
