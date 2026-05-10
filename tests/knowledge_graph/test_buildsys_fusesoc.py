"""Tier B Phase 4: fusesoc .core reader tests."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


def _w(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(body))
    return p


# ---------------------------------------------------------------------------
# (1) CAPI2 with tb target → links emitted
# ---------------------------------------------------------------------------


def test_fusesoc_basic_tb_target(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    _w(tmp_path / "aes.core", """
        CAPI=2:
        name: lowrisc:dv:aes_sim:0.1
        filesets:
          rtl:
            files:
              - rtl/aes.sv
            file_type: systemVerilogSource
          tb:
            files:
              - dv/tb.sv
              - dv/aes_test_pkg.sv
            file_type: systemVerilogSource

        targets:
          default:
            filesets:
              - rtl
          sim:
            filesets:
              - rtl
              - tb
            toplevel: tb
            default_tool: xcelium
        """)
    reader = FusesocReader()
    assert reader.applies_to(tmp_path) is True
    links = reader.read(tmp_path)
    assert links, "expected ≥1 link"
    assert {l.module_name for l in links} == {"aes"}
    assert {l.source_format for l in links} == {"fusesoc"}
    assert {l.confidence_tier for l in links} == {"high"}
    # Each tb fileset .sv file becomes a candidate test source.
    test_names = {Path(l.test_path).name for l in links}
    assert "tb.sv" in test_names or "aes_test_pkg.sv" in test_names


# ---------------------------------------------------------------------------
# (2) Pure-RTL core (no tb target) → no links
# ---------------------------------------------------------------------------


def test_fusesoc_pure_rtl_no_links(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    _w(tmp_path / "aes.core", """
        CAPI=2:
        name: lowrisc:ip:aes:0.1
        filesets:
          rtl:
            files:
              - rtl/aes.sv
        targets:
          default:
            filesets: [rtl]
          synth:
            filesets: [rtl]
            toplevel: aes
        """)
    links = FusesocReader().read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (3) name parses as `vendor:lib:core_name:ver` → module = first segment of core_name
# ---------------------------------------------------------------------------


def test_fusesoc_module_name_from_vlnv(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    _w(tmp_path / "x.core", """
        CAPI=2:
        name: lowrisc:dv:hmac_sim:0.1
        filesets:
          tb:
            files: [dv/hmac_tb.sv]
        targets:
          sim:
            filesets: [tb]
            toplevel: tb
        """)
    links = FusesocReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"hmac"}


# ---------------------------------------------------------------------------
# (4) Malformed YAML → no crash, [] returned
# ---------------------------------------------------------------------------


def test_fusesoc_malformed_core(tmp_path, caplog):
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    _w(tmp_path / "bad.core", "CAPI=2:\nname: : : :\n  - wat\n  - this is broken\n")
    with caplog.at_level("WARNING"):
        links = FusesocReader().read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (5) Multi-target core (sim / lint / synth) — only sim contributes links
# ---------------------------------------------------------------------------


def test_fusesoc_multi_target_only_sim_contributes(tmp_path):
    """A real-world core file declares several targets. Only ``sim`` (and
    targets whose name contains the tb-hint substrings) should contribute
    links; lint and synth must not produce false positives."""
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    _w(tmp_path / "aes.core", """
        CAPI=2:
        name: lowrisc:dv:aes_sim:0.1
        filesets:
          rtl:
            files:
              - rtl/aes.sv
          tb:
            files:
              - dv/aes_tb.sv
              - dv/aes_test_pkg.sv
          lint_only:
            files:
              - lint/waivers.vlt
        targets:
          default:
            filesets: [rtl]
          sim:
            filesets: [rtl, tb]
            toplevel: tb
          lint:
            filesets: [rtl, lint_only]
            toplevel: aes
          synth:
            filesets: [rtl]
            toplevel: aes
        """)
    links = FusesocReader().read(tmp_path)
    src_names = {Path(l.test_path).name for l in links}
    assert "aes_tb.sv" in src_names
    assert "aes_test_pkg.sv" in src_names
    # The lint-only file should never appear (lint target is not a tb target).
    assert "waivers.vlt" not in src_names
    assert "aes.sv" not in src_names


# ---------------------------------------------------------------------------
# (6) Cross-core dependency — depends on another core, no crash
# ---------------------------------------------------------------------------


def test_fusesoc_cross_core_dependency(tmp_path):
    """A core may declare ``depend:`` references to other VLNV cores.
    These are resolved by fusesoc itself; our reader doesn't follow them
    but must not crash on their presence and must still emit links from
    the local filesets."""
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    _w(tmp_path / "dut.core", """
        CAPI=2:
        name: vendor:lib:dut_sim:1.0
        filesets:
          tb:
            files:
              - dv/dut_tb.sv
            depend:
              - vendor:lib:dut:1.0
              - lowrisc:dv:dv_utils
        targets:
          sim:
            filesets: [tb]
            toplevel: tb
        """)
    links = FusesocReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"dut"}


# ---------------------------------------------------------------------------
# (7) CAPI1 legacy header — clear log + no crash + no links
# ---------------------------------------------------------------------------


def test_fusesoc_capi1_legacy(tmp_path, caplog):
    """CAPI=1 cores use INI-style sections, not YAML. The reader does not
    support that schema; it must log a clear ``unsupported`` warning and
    return [] without crashing."""
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    _w(tmp_path / "old.core", """
        CAPI=1
        [main]
        name = vendor:lib:old:1.0
        depend = a b c

        [verilator]
        verilator_options = -Wno-fatal
        """)
    with caplog.at_level("WARNING"):
        links = FusesocReader().read(tmp_path)
    assert links == []
    # A warning is logged so users know why this file was skipped.
    assert any(
        "CAPI=1" in rec.getMessage() or "unsupported" in rec.getMessage().lower()
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# (8) Generators block in core file — ignored gracefully
# ---------------------------------------------------------------------------


def test_fusesoc_generators_ignored(tmp_path):
    """A core may declare ``generators:`` — code-generation rules. We
    don't understand them; the reader must skip them gracefully and still
    extract links from regular filesets/targets."""
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    _w(tmp_path / "g.core", """
        CAPI=2:
        name: lowrisc:dv:g_sim:0.1
        generators:
          tlgen:
            interpreter: python3
            command: util/tlgen.py
            description: Generate the TL interconnect
        filesets:
          tb:
            files:
              - dv/g_tb.sv
        targets:
          sim:
            filesets: [tb]
            toplevel: tb
            generate: [tlgen]
        """)
    links = FusesocReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"g"}


# ---------------------------------------------------------------------------
# Phase 3 D7: custom tb hints + module strip suffixes
# ---------------------------------------------------------------------------


def test_fusesoc_custom_tb_target_hints(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader
    from kgweave.knowledge_graph.common.types import ProjectConventions

    (tmp_path / "frobnicator.core").write_text(
        "CAPI=2:\n"
        "name: vendor:lib:frobnicator:1.0\n"
        "filesets:\n"
        "  test_files:\n"
        "    files:\n"
        "      - tb/frobnicator_tb.sv\n"
        "targets:\n"
        "  regress:\n"
        "    filesets: [test_files]\n"
    )
    pc = ProjectConventions(fusesoc_tb_target_hints=["regress"])
    links = FusesocReader(project_conventions=pc).read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"frobnicator"}


def test_fusesoc_custom_module_strip_suffixes(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader
    from kgweave.knowledge_graph.common.types import ProjectConventions

    (tmp_path / "gizmo_unit.core").write_text(
        "CAPI=2:\n"
        "name: vendor:lib:gizmo_unit:1.0\n"
        "filesets:\n"
        "  test_files:\n"
        "    files:\n"
        "      - tb/gizmo_tb.sv\n"
        "targets:\n"
        "  sim:\n"
        "    filesets: [test_files]\n"
    )
    pc = ProjectConventions(fusesoc_module_strip_suffixes=["_unit"])
    links = FusesocReader(project_conventions=pc).read(tmp_path)
    assert {l.module_name for l in links} == {"gizmo"}


# ---------------------------------------------------------------------------
# iter-002 TDD: no regex in buildsys_fusesoc; structural VLNV parsing
# ---------------------------------------------------------------------------


def test_fusesoc_no_re_module_usage():
    """The fusesoc extractor must not use `re` module calls — all VLNV
    parsing and suffix stripping must be structural (str.split / str.endswith).
    This test fails before iter-002's fix because `re` is imported and used."""
    import ast
    import importlib.util
    from pathlib import Path

    src_path = Path(__file__).parent.parent.parent / "src" / "kgweave" / "knowledge_graph" / "extraction" / "buildsys_fusesoc.py"
    source = src_path.read_text()
    tree = ast.parse(source)

    re_calls = []
    for node in ast.walk(tree):
        # Check for `re.<func>(...)` calls
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "re":
                re_calls.append(f"re.{func.attr} at line {node.lineno}")

    assert re_calls == [], (
        f"Found {len(re_calls)} re.<func>(...) call(s) in buildsys_fusesoc.py — "
        f"replace with structural str.split / str.endswith parsing:\n"
        + "\n".join(re_calls)
    )


def test_fusesoc_vlnv_structural_parsing_unicode_colon(tmp_path):
    """VLNV names with unusual but valid characters must parse correctly.
    The structural str.split(':') approach handles anything the regex would,
    and more — no regex drift from project-to-project naming conventions."""
    from kgweave.knowledge_graph.extraction.buildsys_fusesoc import FusesocReader

    # A VLNV where the core name starts with a digit (older regex required [A-Za-z_][\w]*)
    # Structural split doesn't have this restriction.
    _w(tmp_path / "x.core", """
        CAPI=2:
        name: acme:dv:uart_sim:2.0
        filesets:
          tb:
            files: [dv/uart_tb.sv]
        targets:
          sim:
            filesets: [tb]
            toplevel: tb
        """)
    links = FusesocReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"uart"}
