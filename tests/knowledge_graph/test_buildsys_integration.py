"""Tier B Phase 7: end-to-end integration tests across all five readers."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kgweave.knowledge_graph.common.sw_test_buildsys import (
    SwTestBuildSystemConfig,
    default_readers,
    discover_links,
)


def _w(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# (1) Synthetic project with all five formats — every reader fires
# ---------------------------------------------------------------------------


def test_all_five_readers_fire(tmp_path):
    # dvsim
    _w(tmp_path / "hw" / "ip" / "aes" / "dv" / "aes_sim_cfg.hjson",
       "{\n  name: aes\n  dut: aes\n  tests: [\n    {\n      name: aes_smoke\n    }\n  ]\n}\n")
    # uvm testlist
    _w(tmp_path / "tb" / "aes_test.f",
       "+UVM_TESTNAME=aes_uvm_test\naes_tb.sv\n")
    # fusesoc
    _w(tmp_path / "hw" / "aes.core",
       "CAPI=2:\nname: lowrisc:dv:aes_sim:0.1\nfilesets:\n"
       "  tb:\n    files: [dv/tb.sv]\n"
       "targets:\n  sim:\n    filesets: [tb]\n    toplevel: tb\n")
    # bazel
    _w(tmp_path / "sw" / "BUILD.bazel",
       'opentitan_functest(name="aes_test", srcs=["aes_test.c"], '
       'deps=["//hw/ip/aes:lib"])\n')
    # makefile
    _w(tmp_path / "scripts" / "Makefile",
       "MODULE := aes\nSRCS = aes_make_test.c\n")

    cfg = SwTestBuildSystemConfig(
        dvsim_hjson_enabled=True,
        uvm_testlist_enabled=True,
        fusesoc_enabled=True,
        bazel_enabled=True,
        makefile_enabled=True,
    )
    readers = default_readers(cfg)
    links = discover_links(tmp_path, readers=readers)
    formats = {l.source_format for l in links}
    assert formats == {"dvsim_hjson", "uvm_testlist", "fusesoc", "bazel", "makefile"}, \
        f"missing formats: {formats}"
    # All five should produce at least one aes link.
    for fmt in formats:
        fmt_links = [l for l in links if l.source_format == fmt]
        assert any(l.module_name == "aes" for l in fmt_links), (
            f"format {fmt} has no aes link: {fmt_links}"
        )


# ---------------------------------------------------------------------------
# (2) Precedence: build-system link wins over conflicting regex
# ---------------------------------------------------------------------------


def test_buildsystem_overrides_regex_in_full_pipeline(tmp_path):
    """When a project has both a dvsim hjson AND C tests with regex-matchable
    DIF includes, the build-system link is the one emitted; the regex match
    is suppressed for the same (test, module) pair."""
    from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor

    sw = tmp_path / "sw" / "tests"
    sw.mkdir(parents=True)
    aes_c = sw / "aes_smoke.c"
    aes_c.write_text(
        '#include "dif_aes.h"\n'
        "int main(void){ dif_aes_init(&h); return 0; }\n"
    )

    # dvsim cfg listing this exact test name (basename match → maps to aes_c)
    _w(tmp_path / "hw" / "ip" / "aes" / "dv" / "aes_sim_cfg.hjson",
       "{\n  name: aes\n  dut: aes\n  tests: [\n    {\n      name: aes_smoke\n    }\n  ]\n}\n")

    cfg_bs = SwTestBuildSystemConfig(dvsim_hjson_enabled=True)
    readers = default_readers(cfg_bs)

    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(
        source=str(sw),
        project_root=tmp_path,
        build_system_readers=readers,
    )
    aes_edges = [
        t for t in res.triples
        if t.predicate == "tests_module" and t.object == "aes"
    ]
    # Only one edge — the build-system link suppresses the regex match.
    assert len(aes_edges) == 1
    edge = aes_edges[0]
    assert (edge.attributes or {}).get("build_system_format") == "dvsim_hjson"


# ---------------------------------------------------------------------------
# (3) Build-system + regex coexist for different modules
# ---------------------------------------------------------------------------


def test_buildsystem_complements_regex(tmp_path):
    from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor

    sw = tmp_path / "sw" / "tests"
    sw.mkdir(parents=True)
    # Test that includes both aes and hmac DIF headers.
    (sw / "multi.c").write_text(
        '#include "dif_aes.h"\n#include "dif_hmac.h"\n'
        "int main(void){ return 0; }\n"
    )
    # Build system only knows about aes.
    _w(tmp_path / "hw" / "ip" / "aes" / "dv" / "aes_sim_cfg.hjson",
       "{\n  name: aes\n  dut: aes\n  tests: [\n    {\n      name: multi\n    }\n  ]\n}\n")

    cfg_bs = SwTestBuildSystemConfig(dvsim_hjson_enabled=True)
    ex = SWTestExtractor(known_entity_names=["aes", "hmac"])
    res = ex.extract(
        source=str(sw),
        project_root=tmp_path,
        build_system_readers=default_readers(cfg_bs),
    )
    aes_edges = [t for t in res.triples
                 if t.predicate == "tests_module" and t.object == "aes"]
    hmac_edges = [t for t in res.triples
                  if t.predicate == "tests_module" and t.object == "hmac"]
    assert len(aes_edges) == 1
    assert (aes_edges[0].attributes or {}).get("build_system_format") == "dvsim_hjson"
    assert len(hmac_edges) == 1
    # hmac came from regex — no build_system_format attribute
    assert "build_system_format" not in (hmac_edges[0].attributes or {})
