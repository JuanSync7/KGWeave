"""Fuzz/adversarial-input resilience for SV-text extractors.

Loop-attached requirement for the regex-fragility auto-research loop:
each kept iteration that touches an extractor must extend ``FUZZ_CORPUS``
with an input that the changed extractor previously crashed on (or a fresh
adversarial case proving it now degrades gracefully).

The contract is intentionally narrow: extractors must NOT raise uncaught
exceptions on any input in ``FUZZ_CORPUS``. They are free to return empty
results, log warnings, or otherwise refuse to extract — the only failure
mode this test rejects is unhandled exceptions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.common.types import KGConfig, load_schema
from kgweave.knowledge_graph.extraction.regex_extractor import RegexEntityExtractor
from kgweave.knowledge_graph.extraction.parser_extractor import SVParserExtractor

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "config" / "kg_schema.yaml"


FUZZ_CORPUS: list[tuple[str, str]] = [
    ("empty", ""),
    ("single_byte", "x"),
    ("only_whitespace", "   \n\t\n  "),
    ("nul_bytes", "module foo;\x00\x00endmodule"),
    ("unbalanced_braces", "module foo; { { { endmodule"),
    ("unicode_garbage", "module 𝓯𝓸𝓸; ​‌ endmodule"),
    ("very_long_line", "module foo; " + ("a" * 50000) + " endmodule"),
    ("truncated_module", "module half_decl"),
    ("only_comments", "// just a comment\n/* block */\n"),
    ("backslash_nl_storm", "\\\n" * 1000),
    ("non_sv_content", "#!/usr/bin/env python\nimport os\nprint('hi')\n"),
    ("hjson_lookalike", '{"name": "foo", "modules": [1,2,3]}'),
    ("malformed_directives", "`include\n`define\n`ifdef\n`endif"),
    ("mixed_lineendings", "module foo;\r\nendmodule\r\n"),
    # iter-013: adversarial for sv_connectivity assertion-ident extraction.
    # module keyword with tab separator + parameterized port + multiline
    # concurrent assertion — exposes regex-on-text fragility in old code.
    (
        "tab_sep_module_with_multiline_assertion",
        "module\ttab_mod #(parameter int W=8) (\n"
        "  input logic clk_i, input logic rst_ni,\n"
        "  input logic [W-1:0] req, output logic [W-1:0] ack\n"
        ");\n"
        "  chk: assert property (\n"
        "    @(posedge clk_i) disable iff (!rst_ni) req |-> ##1 ack\n"
        "  );\n"
        "endmodule\n",
    ),
]


@pytest.fixture(scope="module")
def regex_extractor() -> RegexEntityExtractor:
    return RegexEntityExtractor()


@pytest.fixture(scope="module")
def sv_parser_extractor() -> SVParserExtractor:
    pytest.importorskip("pyslang", reason="pyslang required for SVParserExtractor")
    return SVParserExtractor(schema=load_schema(str(SCHEMA_PATH)), config=KGConfig())


@pytest.mark.parametrize("name,text", FUZZ_CORPUS, ids=[c[0] for c in FUZZ_CORPUS])
def test_regex_extractor_does_not_crash(regex_extractor: RegexEntityExtractor, name: str, text: str) -> None:
    result = regex_extractor.extract(text, source=f"fuzz::{name}")
    assert result is not None


@pytest.mark.parametrize("name,text", FUZZ_CORPUS, ids=[c[0] for c in FUZZ_CORPUS])
def test_sv_parser_extractor_does_not_crash(sv_parser_extractor: SVParserExtractor, name: str, text: str) -> None:
    result = sv_parser_extractor.extract(text, source=f"fuzz::{name}")
    assert result is not None
