"""Phase 2 hardcoded-values cleanup: end-to-end ProjectConventions wiring.

Validates that:
  - ``KGConfig(project_conventions=ProjectConventions())`` (strict generic)
    feeds a coherent, empty-but-valid pipeline on a synthetic non-OT
    codebase, AND emits the right warnings.
  - ``KGConfig(project_conventions=ProjectConventions.opentitan())`` keeps
    OT-shaped wiring functional on an OT-shaped fixture.
"""
from __future__ import annotations

import logging
from pathlib import Path
from textwrap import dedent

import pytest

from kgweave.knowledge_graph.common.sw_test_config import load_sw_test_config
from kgweave.knowledge_graph.common.types import KGConfig, ProjectConventions
from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader
from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor


def _w(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(body))
    return p


def test_strict_generic_conventions_emits_warnings_and_no_ot_links(
    tmp_path, caplog
):
    """A KGConfig with strict-generic ProjectConventions feeding a synthetic
    non-OT codebase must:
      - emit a sw_test_config WARNING about producing no links
      - emit zero Bazel module links (no silent OT fallback)
      - emit zero ``tests_module`` regex edges (empty pattern engine)
    """
    cfg = KGConfig(project_conventions=ProjectConventions())
    assert cfg.project_conventions.profile is None

    # Synthetic non-OT layout: a //rtl/<mod> Bazel BUILD and a C test using
    # a generic call shape. None of this should resolve through OT defaults.
    sw_dir = tmp_path / "sw"
    _w(sw_dir / "splork_test.c", '''
        // Generic non-OT C test
        #include "splork.h"
        int main(void) { splork_init(); return 0; }
        ''')
    _w(tmp_path / "BUILD.bazel", '''
        cc_test(
            name = "wibble_unit",
            srcs = ["wibble_unit.cc"],
            deps = ["//rtl/wibble:rtl"],
        )
        ''')

    # ---- 1. sw_test_config: empty + warning ------------------------------
    with caplog.at_level(
        logging.WARNING, logger="rag.knowledge_graph.sw_test_config"
    ):
        sw_cfg = load_sw_test_config(
            None, project_conventions=cfg.project_conventions
        )
    assert sw_cfg.patterns == []
    assert any(
        "produce no links" in rec.getMessage().lower()
        for rec in caplog.records
    ), "expected a strict-generic warning from sw_test_config"

    # ---- 2. Bazel reader: zero links + warning ---------------------------
    caplog.clear()
    with caplog.at_level(
        logging.WARNING, logger="rag.knowledge_graph.buildsys_bazel"
    ):
        bazel = BazelBuildReader(project_conventions=cfg.project_conventions)
    bazel_links = bazel.read(tmp_path)
    assert bazel_links == []
    assert any(
        "no dep_module_pattern" in rec.getMessage().lower()
        for rec in caplog.records
    ), "expected a strict-generic warning from BazelBuildReader"

    # ---- 3. SWTestExtractor: zero tests_module edges (empty patterns) ----
    ex = SWTestExtractor(
        known_entity_names=["splork", "wibble"],
        sw_test_config=sw_cfg,
        project_conventions=cfg.project_conventions,
    )
    res = ex.extract(source=str(sw_dir))
    pattern_resolved = [
        t for t in res.triples
        if t.predicate == "tests_module" and t.resolved
    ]
    # Zero high/medium-tier resolved edges — no OT-shaped pattern matched.
    assert pattern_resolved == [], (
        f"expected no spurious OT-shaped tests_module edges, "
        f"got {[(t.subject, t.object) for t in pattern_resolved]}"
    )
    # Sentinel low-tier <unknown> edges may exist for files that hit a
    # marker, but no resolved high-tier OT links should sneak in.
    sw_tests = {e.name for e in res.entities if e.type == "SW_Test"}
    assert "splork_test" in sw_tests, "SW_Test entity should still emit"


def test_opentitan_conventions_preserves_ot_pattern_resolution(tmp_path):
    """Symmetric check: ProjectConventions.opentitan() keeps OT-pattern
    resolution working on an OT-shaped fixture (no regression vs. the
    legacy bare-call default)."""
    pc = ProjectConventions.opentitan()
    sw_cfg = load_sw_test_config(None, project_conventions=pc)
    assert sw_cfg.patterns, "OT profile must keep OT default patterns"

    sw_dir = tmp_path / "sw"
    sw_dir.mkdir()
    (sw_dir / "ot_smoke.c").write_text(
        '#include "dif_aes.h"\n'
        "int main(void) { dif_aes_init(&h); return 0; }\n"
    )
    ex = SWTestExtractor(
        known_entity_names=["aes"],
        sw_test_config=sw_cfg,
        project_conventions=pc,
    )
    res = ex.extract(source=str(sw_dir))
    edges = [
        t for t in res.triples
        if t.predicate == "tests_module" and t.resolved and t.object == "aes"
    ]
    assert edges, "OT profile must still resolve dif_<mod> patterns"

    # And Bazel reader sourced from the OT profile resolves //hw/ip layout.
    _w(tmp_path / "BUILD.bazel", '''
        opentitan_functest(
            name = "aes_smoke",
            srcs = ["aes_smoke.c"],
            deps = ["//hw/ip/aes:dif"],
        )
        ''')
    bazel = BazelBuildReader(project_conventions=pc)
    links = bazel.read(tmp_path)
    assert {l.module_name for l in links} == {"aes"}
