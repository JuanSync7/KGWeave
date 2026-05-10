"""Tier B Phase 3: UVM testlist .f file reader tests.

A UVM testlist .f file mixes simulator command-line args with file paths.
The reader extracts:
  - +UVM_TESTNAME=<test_name> entries → test names
  - .sv testbench file paths → module-name inferred from basename heuristic
  - -f sub.f recursive includes (depth-limited; cycle-safe)
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest


def _w(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# (1) Basic: +UVM_TESTNAME and a tb.sv path
# ---------------------------------------------------------------------------


def test_uvm_testlist_basic(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "aes_test.f", """
+UVM_TESTNAME=aes_smoke_vseq
+UVM_TESTNAME=aes_stress_vseq
${PROJ}/hw/ip/aes/dv/aes_tb.sv
""")
    reader = UvmTestlistReader()
    assert reader.applies_to(tmp_path) is True
    links = reader.read(tmp_path)
    assert links, "expected at least one link"
    # All links infer module 'aes' from aes_tb.sv basename heuristic.
    assert {l.module_name for l in links} == {"aes"}
    # Confidence should be medium (heuristic).
    assert {l.confidence_tier for l in links} == {"medium"}
    # Each UVM_TESTNAME becomes a separate link.
    test_names = {Path(l.test_path).name for l in links}
    assert "aes_smoke_vseq" in test_names
    assert "aes_stress_vseq" in test_names


# ---------------------------------------------------------------------------
# (2) Comments ignored
# ---------------------------------------------------------------------------


def test_uvm_testlist_ignores_comments(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "x.f", """
// disabled: +UVM_TESTNAME=ignored_test
# also a comment +UVM_TESTNAME=ignored2
+UVM_TESTNAME=real_test
hmac_tb.sv
""")
    links = UvmTestlistReader().read(tmp_path)
    test_names = {Path(l.test_path).name for l in links}
    assert "real_test" in test_names
    assert "ignored_test" not in test_names
    assert "ignored2" not in test_names


# ---------------------------------------------------------------------------
# (3) -f recursive include
# ---------------------------------------------------------------------------


def test_uvm_testlist_f_includes(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "main.f", """
-f sub.f
+UVM_TESTNAME=top_test
""")
    _w(tmp_path / "sub.f", """
+UVM_TESTNAME=sub_test
aes_tb.sv
""")
    links = UvmTestlistReader().read(tmp_path)
    # links from BOTH files via the recursive include
    by_name = {Path(l.test_path).name for l in links}
    assert "sub_test" in by_name
    assert "top_test" in by_name


# ---------------------------------------------------------------------------
# (4) -f cycle is bounded (no stack overflow)
# ---------------------------------------------------------------------------


def test_uvm_testlist_f_cycle_safe(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "a.f", "-f b.f\n+UVM_TESTNAME=t_a\n")
    _w(tmp_path / "b.f", "-f a.f\n+UVM_TESTNAME=t_b\naes_tb.sv\n")
    # Should not infinite-loop.
    links = UvmTestlistReader().read(tmp_path)
    by_name = {Path(l.test_path).name for l in links}
    assert "t_a" in by_name
    assert "t_b" in by_name


# ---------------------------------------------------------------------------
# (5) No tb file → no module inferred → no links
# ---------------------------------------------------------------------------


def test_uvm_testlist_no_tb_file_yields_no_links(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "x.f", "+UVM_TESTNAME=lonely_test\n")
    links = UvmTestlistReader().read(tmp_path)
    # No tb.sv → no module → emit no links (a UVM testname without a
    # testbench file is unusable for module resolution).
    assert links == []


# ---------------------------------------------------------------------------
# (6) applies_to: False when no .f files
# ---------------------------------------------------------------------------


def test_uvm_testlist_applies_to_false(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    (tmp_path / "x.txt").write_text("hi")
    assert UvmTestlistReader().applies_to(tmp_path) is False


# ---------------------------------------------------------------------------
# (7) VCS-flavored .f file: -l logfile, -ntb_opts, +UVM_TESTNAME
# ---------------------------------------------------------------------------


def test_uvm_testlist_vcs_flavored(tmp_path):
    """VCS-style invocation files mix simulator switches like
    ``-l <logfile>`` and ``-ntb_opts uvm-1.2`` with the UVM testname
    plusarg. The reader should ignore unknown switches and still pull
    out the testname + tb."""
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "vcs_run.f", """
-l simv.log
-ntb_opts uvm-1.2
-timescale=1ns/1ps
-debug_access+all
+UVM_TESTNAME=aes_smoke_test
+UVM_VERBOSITY=UVM_HIGH
${PROJ}/hw/ip/aes/dv/aes_tb.sv
""")
    links = UvmTestlistReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"aes"}
    test_names = {Path(l.test_path).name for l in links}
    assert "aes_smoke_test" in test_names


# ---------------------------------------------------------------------------
# (8) Mixed plusargs — only +UVM_TESTNAME extracted, +UVM_VERBOSITY etc skipped
# ---------------------------------------------------------------------------


def test_uvm_testlist_mixed_plusargs(tmp_path):
    """A line with several +foo=bar plusargs must yield only the
    +UVM_TESTNAME entry as a test name; other plusargs are simulator
    knobs, not tests."""
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "mixed.f", """
+UVM_VERBOSITY=HIGH +UVM_TESTNAME=hmac_perf_test +UVM_NO_RELNOTES=1
hmac_tb.sv
""")
    links = UvmTestlistReader().read(tmp_path)
    test_names = {Path(l.test_path).name for l in links}
    assert "hmac_perf_test" in test_names
    # Verbosity / NO_RELNOTES are not test names.
    assert "HIGH" not in test_names
    assert "1" not in test_names
    # Only one link emitted (one testname × one tb module).
    assert len(links) == 1


# ---------------------------------------------------------------------------
# (9) `--` style comments (some sims use ada-style)
# ---------------------------------------------------------------------------


def test_uvm_testlist_dashdash_comment(tmp_path):
    """Some lint/test wrappers emit ``--`` line-comments. Treat them like
    ``#`` and ``//``: ignore the entire line."""
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "x.f", """
-- disabled: +UVM_TESTNAME=skip_me
+UVM_TESTNAME=keep_me
aes_tb.sv
""")
    links = UvmTestlistReader().read(tmp_path)
    test_names = {Path(l.test_path).name for l in links}
    assert "keep_me" in test_names
    assert "skip_me" not in test_names


# ---------------------------------------------------------------------------
# (10) Recursive -f with relative paths spanning subdirs
# ---------------------------------------------------------------------------


def test_uvm_testlist_recursive_f_relative_paths(tmp_path):
    """``-f sub/file.f`` with a relative path nested in a subdirectory
    should resolve relative to the including .f file's parent dir, and
    the included file's own ``-f ../other.f`` also resolves relatively."""
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "top.f", """
-f sub/inner.f
+UVM_TESTNAME=top_test
""")
    _w(tmp_path / "sub" / "inner.f", """
-f ../sibling.f
+UVM_TESTNAME=inner_test
""")
    _w(tmp_path / "sibling.f", """
+UVM_TESTNAME=sibling_test
aes_tb.sv
""")
    links = UvmTestlistReader().read(tmp_path)
    by_name = {Path(l.test_path).name for l in links}
    # All three test names should be reachable via the recursive resolution.
    assert "top_test" in by_name
    assert "inner_test" in by_name
    assert "sibling_test" in by_name


# ---------------------------------------------------------------------------
# Phase 3 D8: custom testbench filename regex
# ---------------------------------------------------------------------------


def test_uvm_testlist_custom_testbench_filename_regex(tmp_path):
    """A non-OT codebase uses ``<module>_testbench.sv`` instead of
    ``<module>_tb.sv``. The reader must extract the module via the
    custom regex."""
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )
    from kgweave.knowledge_graph.common.types import ProjectConventions

    (tmp_path / "tests.f").write_text(
        "+UVM_TESTNAME=frob_smoke\n"
        "frob_testbench.sv\n"
    )
    pc = ProjectConventions(
        uvm_testbench_filename_suffix="_testbench.sv"
    )
    links = UvmTestlistReader(project_conventions=pc).read(tmp_path)
    mods = {l.module_name for l in links}
    assert "frob" in mods


# ---------------------------------------------------------------------------
# iter-004: structural-only parser — no import re
# ---------------------------------------------------------------------------


def test_uvm_testlist_no_regex_import():
    """The buildsys_uvm_testlist module must not import the re module at all.

    This test was added alongside the iter-004 structural rewrite.
    It would fail on the pre-004 code that used re.compile for all four
    patterns.
    """
    import kgweave.knowledge_graph.extraction.buildsys_uvm_testlist as mod

    source = inspect.getsource(mod)
    assert "import re" not in source, (
        "buildsys_uvm_testlist still imports 're'; replace with structural parsing"
    )


def test_uvm_testlist_tab_separated_uvm_testname(tmp_path):
    """A tab-separated line ``+UVM_TESTNAME=<name>`` (instead of space) must
    still be parsed correctly by the structural token splitter.

    The old regex would have matched this trivially; the structural rewrite
    must handle it too (split on whitespace covers tabs).
    """
    from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
        UvmTestlistReader,
    )

    _w(tmp_path / "tabbed.f", "+UVM_TESTNAME=tabbed_test\taes_tb.sv\n")
    links = UvmTestlistReader().read(tmp_path)
    test_names = {Path(l.test_path).name for l in links}
    assert "tabbed_test" in test_names
    assert {l.module_name for l in links} == {"aes"}
