"""Tests for BashParserExtractor structural (non-regex) implementation.

TDD guard: these tests were added before the regex removal to verify that
the parser works correctly with pure structural token inspection instead of
``re.compile`` / ``re.match`` patterns.

The test ``test_no_re_import`` will FAIL until ``bash_parser.py`` no longer
imports the ``re`` module.
"""
from __future__ import annotations

import ast
import importlib
import textwrap
from pathlib import Path

import pytest

from kgweave.knowledge_graph.extraction.bash_parser import BashParserExtractor

# ---------------------------------------------------------------------------
# Smoke test: no re import in bash_parser module
# ---------------------------------------------------------------------------

def test_no_re_import() -> None:
    """bash_parser.py must not import the ``re`` module (structural parser only)."""
    src_path = Path(__file__).parent.parent.parent / "src" / "kgweave" / "knowledge_graph" / "extraction" / "bash_parser.py"
    tree = ast.parse(src_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "re", (
                    "bash_parser.py still imports 're' — regex not yet removed"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "re", (
                "bash_parser.py still imports from 're' — regex not yet removed"
            )


# ---------------------------------------------------------------------------
# Structural parsing correctness
# ---------------------------------------------------------------------------

def test_function_styles_extracted() -> None:
    """Both ``function foo()`` and bare ``foo()`` styles should be found."""
    src = textwrap.dedent("""\
        #!/bin/bash
        function run_synth() {
            echo synth
        }
        run_sim() {
            echo sim
        }
    """)
    ext = BashParserExtractor()
    result = ext.extract(src, source="flow.sh")
    names = {e.name for e in result.entities if e.type == "BashFunction"}
    assert "run_synth" in names, f"run_synth missing; got {names}"
    assert "run_sim" in names, f"run_sim missing; got {names}"


def test_source_variants_extracted() -> None:
    """Both ``source`` and dot ``.`` forms should produce depends_on triples."""
    src = textwrap.dedent("""\
        source ./helpers.sh
        . /etc/profile.d/setup.sh
    """)
    ext = BashParserExtractor()
    result = ext.extract(src, source="run.sh")
    dep_objs = {t.object for t in result.triples if t.predicate == "depends_on"}
    assert "helpers" in dep_objs, f"helpers missing; got {dep_objs}"
    assert "setup" in dep_objs, f"setup missing; got {dep_objs}"


def test_export_extracted() -> None:
    """``export FOO=bar`` should produce a BashVariable entity."""
    src = "export TOOL_VERSION=1.2\n"
    ext = BashParserExtractor()
    result = ext.extract(src, source="env.sh")
    names = {e.name for e in result.entities if e.type == "BashVariable"}
    assert "TOOL_VERSION" in names, f"TOOL_VERSION missing; got {names}"


def test_readonly_extracted() -> None:
    """``readonly VAR=val`` and ``declare -r VAR=val`` should produce BashVariable."""
    src = textwrap.dedent("""\
        readonly BUILD_DIR=/out
        declare -r REPORT_DIR=/rpt
    """)
    ext = BashParserExtractor()
    result = ext.extract(src, source="setup.sh")
    names = {e.name for e in result.entities if e.type == "BashVariable"}
    assert "BUILD_DIR" in names, f"BUILD_DIR missing; got {names}"
    assert "REPORT_DIR" in names, f"REPORT_DIR missing; got {names}"


def test_source_variable_expansion_skipped() -> None:
    """``source $VAR/lib.sh`` must NOT produce a BashScript entity (ambiguous path)."""
    src = "source $FLOW_ROOT/lib.sh\n"
    ext = BashParserExtractor()
    result = ext.extract(src, source="run.sh")
    script_names = {e.name for e in result.entities if e.type == "BashScript"}
    assert not script_names, (
        f"Variable-expanded source should be skipped, got: {script_names}"
    )


def test_empty_input() -> None:
    """Empty input returns an empty ExtractionResult without crashing."""
    ext = BashParserExtractor()
    result = ext.extract("", source="empty.sh")
    assert result.entities == []
    assert result.triples == []


def test_comment_lines_ignored() -> None:
    """Lines starting with ``#`` should not produce false-positive function entities."""
    src = textwrap.dedent("""\
        # function fake_fn() { echo nope; }
        # export NOT_A_VAR=value
        real_fn() { echo yes; }
    """)
    ext = BashParserExtractor()
    result = ext.extract(src, source="commented.sh")
    names = {e.name for e in result.entities if e.type == "BashFunction"}
    assert "fake_fn" not in names, f"Comment should be ignored; got {names}"
    assert "real_fn" in names, f"real_fn should be extracted; got {names}"
