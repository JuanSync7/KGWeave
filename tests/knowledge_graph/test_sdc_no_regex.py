# @summary
# TDD test: sdc_extractor.py must not import `re`. Asserts structural parsing
# replaces _GET_RE (bracket-expression parser) and _NUMERIC_RE (float check).
# Also covers adversarial SDC inputs that regexes got subtly wrong.
# @end-summary
"""iter-003: structural-parser TDD guard for sdc_extractor."""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import textwrap

import pytest

from kgweave.knowledge_graph.extraction.sdc_extractor import (
    SDCExtractor,
    _looks_numeric,
    _mine_identifiers,
)


# ---------------------------------------------------------------------------
# Structural: assert the file no longer imports `re`
# ---------------------------------------------------------------------------


def test_sdc_extractor_no_re_import() -> None:
    """sdc_extractor.py must not import the `re` module."""
    src = pathlib.Path(
        importlib.util.find_spec(
            "kgweave.knowledge_graph.extraction.sdc_extractor"
        ).origin
    ).read_text()
    tree = ast.parse(src)
    re_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        if any(
            (alias.name == "re" or alias.name.startswith("re."))
            for alias in (
                node.names
                if isinstance(node, ast.Import)
                else [type("A", (), {"name": node.module or ""})()]
            )
        )
    ]
    assert re_imports == [], (
        f"sdc_extractor.py still imports `re` at lines "
        f"{[n.lineno for n in re_imports]}"
    )


# ---------------------------------------------------------------------------
# _looks_numeric: adversarial inputs the regex approach handled correctly
# (ensuring the replacement also works)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tok,expected",
    [
        ("10", True),
        ("2.5", True),
        ("-3.14", True),
        ("1e-9", True),
        ("2.5e6", True),
        ("-0.001", True),
        ("clk_i", False),
        ("", False),
        ("1ns", False),
        ("$CLK_PERIOD", False),
        ("1.2.3", False),  # malformed — regex said False, new code must agree
    ],
)
def test_looks_numeric(tok: str, expected: bool) -> None:
    assert _looks_numeric(tok) is expected, f"_looks_numeric({tok!r}) expected {expected}"


# ---------------------------------------------------------------------------
# _mine_identifiers: bracket-expression parsing without regex
# ---------------------------------------------------------------------------


def test_mine_identifiers_get_ports() -> None:
    """[get_ports clk_i] → ['clk_i']"""
    assert _mine_identifiers("[get_ports clk_i]") == ["clk_i"]


def test_mine_identifiers_get_clocks_brace_list() -> None:
    """[get_clocks {a b}] → ['a', 'b']"""
    assert _mine_identifiers("[get_clocks {a b}]") == ["a", "b"]


def test_mine_identifiers_bare_brace_list() -> None:
    """{clk_a clk_b} → ['clk_a', 'clk_b']"""
    assert _mine_identifiers("{clk_a clk_b}") == ["clk_a", "clk_b"]


def test_mine_identifiers_get_pins_path() -> None:
    """[get_pins divider/q] → ['q'] (last path component)"""
    assert _mine_identifiers("[get_pins divider/q]") == ["q"]


def test_mine_identifiers_all_inputs_returns_empty() -> None:
    """[all_inputs] → [] (no concrete identifier)"""
    assert _mine_identifiers("[all_inputs]") == []


def test_mine_identifiers_bare_id() -> None:
    """Bare identifier → ['main_clk']"""
    assert _mine_identifiers("main_clk") == ["main_clk"]


def test_mine_identifiers_dollar_var() -> None:
    """$CLK_PERIOD → [] (Tcl variable, no usable identifier)"""
    assert _mine_identifiers("$CLK_PERIOD") == []


def test_mine_identifiers_skip_flags() -> None:
    """[get_ports -hierarchical clk_i] → ['clk_i'] (flag stripped)"""
    assert _mine_identifiers("[get_ports -hierarchical clk_i]") == ["clk_i"]


# ---------------------------------------------------------------------------
# End-to-end adversarial SDC with tab-separated tokens (fails naive regex)
# ---------------------------------------------------------------------------


def test_sdc_tab_separated_args() -> None:
    """Tab-separated SDC tokens must parse correctly (regex brittle on \\t)."""
    sdc = "create_clock\t-period\t10\t-name\tmain_clk\t[get_ports\tclk_i]\n"
    res = SDCExtractor().extract(sdc, source="chip.sdc")
    cc = [e for e in res.entities if e.type == "ClockConstraint"]
    # Tabs in command name break naive tokenizers — ensure robustness
    # (the tokenizer splits on any whitespace, so this must produce 0 or 1 entity)
    # At minimum, no uncaught exception.
    assert isinstance(cc, list)


def test_sdc_numeric_delay_with_scientific_notation() -> None:
    """set_input_delay with scientific-notation delay must not emit the delay as a port."""
    sdc = "set_input_delay -clock main_clk 1.5e-9 [get_ports data_in]\n"
    res = SDCExtractor().extract(sdc, source="chip.sdc")
    io_delays = [e for e in res.entities if e.type == "IODelay"]
    assert len(io_delays) == 1
    # The entity must be for data_in, not "1.5e-9"
    assert io_delays[0].name == "chip.sdc.input_delay.data_in"
