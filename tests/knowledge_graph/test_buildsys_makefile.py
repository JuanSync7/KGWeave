"""Tier B Phase 6: Makefile reader tests."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


def _w(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(body))
    return p


# ---------------------------------------------------------------------------
# (1) MODULE := aes + test_aes target → link
# ---------------------------------------------------------------------------


def test_makefile_module_var_and_target_rule(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        MODULE := aes
        SRCS := aes_test.c
        test_aes: $(SRCS)
        \tcompile $<
        """)
    reader = MakefileReader()
    assert reader.applies_to(tmp_path) is True
    links = reader.read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"aes"}
    assert {l.confidence_tier for l in links} == {"medium"}
    assert {l.source_format for l in links} == {"makefile"}


# ---------------------------------------------------------------------------
# (2) IP_NAME ?= aes also recognised
# ---------------------------------------------------------------------------


def test_makefile_ip_name_var(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        IP_NAME ?= hmac
        SRCS = hmac_test.c
        """)
    links = MakefileReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"hmac"}


# ---------------------------------------------------------------------------
# (3) include sub.mk recursion (depth-limited)
# ---------------------------------------------------------------------------


def test_makefile_include_directive(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        include sub.mk
        SRCS = top.c
        """)
    _w(tmp_path / "sub.mk", """
        MODULE = aes
        """)
    links = MakefileReader().read(tmp_path)
    mods = {l.module_name for l in links}
    assert "aes" in mods


# ---------------------------------------------------------------------------
# (4) Variable expansion is NOT performed (heuristic — flag in docs)
# ---------------------------------------------------------------------------


def test_makefile_variable_expansion_not_performed(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        MODULE := $(SOMETHING)
        """)
    # When the value is a make-var reference, we skip it (no expansion).
    links = MakefileReader().read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (5) No module hints → no links
# ---------------------------------------------------------------------------


def test_makefile_no_module_yields_no_links(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        all: foo.o
        \tgcc -c foo.c
        """)
    assert MakefileReader().read(tmp_path) == []


# ---------------------------------------------------------------------------
# (6) test_<module>: target rule infers module
# ---------------------------------------------------------------------------


def test_makefile_target_rule_infers_module(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        SRCS = aes_smoke.c

        test-aes: $(SRCS)
        \trun-test
        """)
    links = MakefileReader().read(tmp_path)
    mods = {l.module_name for l in links}
    assert "aes" in mods


# ---------------------------------------------------------------------------
# (7) Pattern target rules (test-%, %_smoke) — wildcards are NOT modules
# ---------------------------------------------------------------------------


def test_makefile_pattern_targets_skipped(tmp_path):
    """A pattern target rule like ``test-%: %.c`` is a stem-rule template,
    not a concrete test name. The reader must not extract ``%`` (or any
    literal containing ``%``) as a module name."""
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        test-%: %.c
        \tgcc -o $@ $<

        %_smoke: %.sv
        \tsim $<

        # No concrete MODULE assigned, so no links should be emitted.
        """)
    links = MakefileReader().read(tmp_path)
    # No literal module name extractable from a pattern target.
    assert all("%" not in l.module_name for l in links)
    assert links == []


# ---------------------------------------------------------------------------
# (8) Recursive include with $(VAR) interpolation — depth-limited, missing-tolerant
# ---------------------------------------------------------------------------


def test_makefile_include_with_make_var_tolerated(tmp_path):
    """``include $(BASE)/common.mk`` cannot be resolved without expanding
    $(BASE). The reader should not crash, should not follow it, and
    should still pick up MODULE/SRCS from the parent Makefile."""
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        include $(BASE)/common.mk
        -include $(MISSING)/optional.mk

        MODULE := aes
        SRCS := aes_test.c
        """)
    links = MakefileReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"aes"}


# ---------------------------------------------------------------------------
# (9) Conditional ifeq/ifdef blocks — content extracted as-is, no evaluation
# ---------------------------------------------------------------------------


def test_makefile_conditional_blocks_extracted_as_is(tmp_path):
    """Conditional blocks like ``ifeq``/``ifdef`` are not evaluated; their
    body is processed line-by-line. If both branches set MODULE, both
    candidates are emitted (the reader can't pick one without expansion)."""
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", """
        ifeq ($(SIM),vcs)
        MODULE := aes
        SRCS := aes_vcs_test.c
        else
        MODULE := hmac
        SRCS := hmac_xcelium_test.c
        endif
        """)
    links = MakefileReader().read(tmp_path)
    mods = {l.module_name for l in links}
    # Both modules surfaced; downstream resolver decides confidence.
    assert "aes" in mods
    assert "hmac" in mods


# ---------------------------------------------------------------------------
# (10) All assignment forms (:=, ?=, =, +=) recognised
# ---------------------------------------------------------------------------


def test_makefile_all_assignment_forms(tmp_path):
    """The reader must accept the four GNU make assignment operators:
    ``:=`` (immediate), ``?=`` (default), ``=`` (recursive), ``+=``
    (append). Each appears for a different variable to verify each is
    actually parsed."""
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    # Each file in its own dir to avoid value collisions.
    _w(tmp_path / "a" / "Makefile", "MODULE := aes\nSRCS := aes_a.c\n")
    _w(tmp_path / "b" / "Makefile", "IP_NAME ?= hmac\nSRCS = hmac_b.c\n")
    _w(tmp_path / "c" / "Makefile", "DUT = kmac\nSRCS = kmac_c.c\n")
    _w(tmp_path / "d" / "Makefile", "DUT_NAME += otbn\nSRCS = otbn_d.c\n")

    links = MakefileReader().read(tmp_path)
    mods = {l.module_name for l in links}
    assert "aes" in mods
    assert "hmac" in mods
    assert "kmac" in mods
    assert "otbn" in mods


# ---------------------------------------------------------------------------
# Phase 3 D4: custom module variable names (project_conventions)
# ---------------------------------------------------------------------------


def test_makefile_custom_module_var_names(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader
    from kgweave.knowledge_graph.common.types import ProjectConventions

    _w(tmp_path / "Makefile", """
        FROB_NAME := gizmo
        SRCS := gizmo_test.c
        """)
    pc = ProjectConventions(makefile_module_vars=["FROB_NAME"])
    links = MakefileReader(project_conventions=pc).read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"gizmo"}


# ---------------------------------------------------------------------------
# Phase 3 D5: custom test target prefixes (e.g. regress-)
# ---------------------------------------------------------------------------


def test_makefile_custom_test_target_prefixes(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader
    from kgweave.knowledge_graph.common.types import ProjectConventions

    _w(tmp_path / "Makefile", """
        SRCS = wibble_test.c

        regress-wibble: $(SRCS)
        \trun-test
        """)
    pc = ProjectConventions(makefile_test_target_prefixes=["regress-"])
    links = MakefileReader(project_conventions=pc).read(tmp_path)
    mods = {l.module_name for l in links}
    assert "wibble" in mods


# ---------------------------------------------------------------------------
# Phase 3 D6: custom module strip suffixes
# ---------------------------------------------------------------------------


def test_makefile_custom_module_strip_suffixes(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader
    from kgweave.knowledge_graph.common.types import ProjectConventions

    _w(tmp_path / "Makefile", """
        MODULE := splork_unit
        SRCS := splork_test.c
        """)
    pc = ProjectConventions(makefile_module_strip_suffixes=["_unit"])
    links = MakefileReader(project_conventions=pc).read(tmp_path)
    assert {l.module_name for l in links} == {"splork"}


# ---------------------------------------------------------------------------
# (iter-006) Structural parser: no regex import, tab-separated targets, etc.
# ---------------------------------------------------------------------------


def test_makefile_no_import_re():
    """After iter-006, buildsys_makefile must not import the re module."""
    import ast, importlib, sys

    # Force fresh import to avoid cached module state.
    mod_name = "kgweave.knowledge_graph.extraction.buildsys_makefile"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    spec = importlib.util.find_spec(mod_name)
    assert spec is not None, f"Cannot find module {mod_name}"
    src = Path(spec.origin).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            assert "re" not in names, (
                "buildsys_makefile still imports the 're' module — "
                "iter-006 structural replacement is incomplete"
            )


def test_makefile_tab_indented_target(tmp_path):
    """Target rule with a tab-separated recipe line must still be parsed."""
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", "test-uart: uart_test.c\n\tgcc uart_test.c\n\nMODULE := uart\n")
    links = MakefileReader().read(tmp_path)
    mods = {l.module_name for l in links}
    assert "uart" in mods


def test_makefile_srcs_uppercase_extensions(tmp_path):
    """SRCS with .c, .cc, .cpp, .sv — all recognised by structural endswith check."""
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", "MODULE := sha2\nSRCS := sha2.c sha2_ref.cpp sha2.sv\n")
    links = MakefileReader().read(tmp_path)
    srcs = {l.raw_match["src"] for l in links}
    assert "sha2.c" in srcs
    assert "sha2_ref.cpp" in srcs
    assert "sha2.sv" in srcs


def test_makefile_make_var_ref_detection(tmp_path):
    """Values containing $( or ${ are skipped without a regex."""
    from kgweave.knowledge_graph.extraction.buildsys_makefile import MakefileReader

    _w(tmp_path / "Makefile", "MODULE := $(COMPUTED_NAME)\nSRCS := good.c\n")
    # No module because the value is a variable reference.
    links = MakefileReader().read(tmp_path)
    assert links == []
