# @summary
# TDD: SVParserExtractor swap from tree-sitter-verilog to pyslang.
# Validates that the seven OpenTitan AES files which previously emitted
# tree-sitter ERROR nodes (and thus zero entities) now emit at least one
# RTL_Module entity. Also includes a round-trip integration test that
# pushes extracted entities + contains edges through NetworkXBackend and
# reads them back via get_outgoing_edges.
#
# INTEGRATION-TEST CONVENTION (project-wide, post connects_to/drives bug):
# Any extractor that produces triples MUST have at least one round-trip
# test that drives the triples through a backend (NetworkXBackend by
# default) and asserts the edges survive storage with their predicate
# intact. The connects_to / drives bug — where two parallel edges between
# the same node pair silently collapsed into one — was only catchable at
# the storage layer, not at extractor unit-test level. Co-locate these
# round-trip tests with the extractor tests so regressions surface fast.
# @end-summary
"""Tests for SVParserExtractor (pyslang-backed SV parser)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.types import KGConfig, load_schema
from kgweave.knowledge_graph.extraction import SVParserExtractor

pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


# -----------------------------------------------------------------------------
# Fixtures / helpers
# -----------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "config" / "kg_schema.yaml"

OT_AES_RTL = Path(
    os.environ.get(
        "KGWEAVE_OPENTITAN_ROOT",
        str(Path.home() / "RagWeave" / "opentitan_data"),
    )
) / "hw" / "ip" / "aes" / "rtl"

PREVIOUSLY_FAILING = [
    "aes_control.sv",
    "aes_core.sv",
    "aes_ctrl_reg_shadowed.sv",
    "aes_ghash.sv",
    "aes_key_expand.sv",
    "aes_sbox.sv",
    "aes_sub_bytes.sv",
]


def _make_parser() -> SVParserExtractor:
    schema = load_schema(str(SCHEMA_PATH))
    config = KGConfig()
    return SVParserExtractor(schema=schema, config=config)


# -----------------------------------------------------------------------------
# OpenTitan corpus — previously-failing files now emit modules
# -----------------------------------------------------------------------------


@pytest.mark.skipif(
    not OT_AES_RTL.exists(), reason="OpenTitan AES corpus unavailable"
)
@pytest.mark.parametrize("filename", PREVIOUSLY_FAILING)
def test_pyslang_parses_previously_failing_aes_files(filename: str) -> None:
    """The 7 files that tree-sitter-verilog emitted ERROR nodes on must
    now produce at least one RTL_Module entity each.
    """
    parser = _make_parser()
    path = OT_AES_RTL / filename
    result = parser.extract(text=path.read_text(errors="replace"), source=str(path))
    modules = [e for e in result.entities if e.type == "RTL_Module"]
    assert modules, (
        f"No RTL_Module emitted for {filename} — pyslang parser failing"
    )


# -----------------------------------------------------------------------------
# Synthetic-source unit tests — entity / triple shape
# -----------------------------------------------------------------------------


SIMPLE_MODULE = """
module my_mod #(
    parameter int W = 8,
    parameter int D = 4
)(
    input  wire             clk,
    input  wire             rst_n,
    output logic [W-1:0]    q,
    inout  wire             io
);
    wire [3:0] s, t;
    logic x, y;
    bar #(.W(4)) u_bar (.clk(clk));
    baz u_baz (.a(s));
endmodule
"""


def test_simple_module_emits_module_entity() -> None:
    parser = _make_parser()
    result = parser.extract(SIMPLE_MODULE, source="test.sv")
    names = {(e.name, e.type) for e in result.entities}
    assert ("my_mod", "RTL_Module") in names


def test_simple_module_emits_namespaced_ports() -> None:
    parser = _make_parser()
    result = parser.extract(SIMPLE_MODULE, source="test.sv")
    ports = {e.name for e in result.entities if e.type == "Port"}
    assert "my_mod.clk" in ports
    assert "my_mod.rst_n" in ports
    assert "my_mod.q" in ports
    assert "my_mod.io" in ports


def test_simple_module_emits_namespaced_parameters() -> None:
    parser = _make_parser()
    result = parser.extract(SIMPLE_MODULE, source="test.sv")
    params = {e.name for e in result.entities if e.type == "Parameter"}
    assert "my_mod.W" in params
    assert "my_mod.D" in params


def test_simple_module_emits_namespaced_signals() -> None:
    parser = _make_parser()
    result = parser.extract(SIMPLE_MODULE, source="test.sv")
    signals = {e.name for e in result.entities if e.type == "Signal"}
    # Wire and logic declarators inside the body — multi-name decls expand.
    assert "my_mod.s" in signals
    assert "my_mod.t" in signals
    assert "my_mod.x" in signals
    assert "my_mod.y" in signals


def test_simple_module_emits_instance_and_instantiates() -> None:
    parser = _make_parser()
    result = parser.extract(SIMPLE_MODULE, source="test.sv")
    insts = {e.name for e in result.entities if e.type == "Instance"}
    assert "my_mod.u_bar" in insts
    assert "my_mod.u_baz" in insts

    instantiates = {
        (t.subject, t.predicate, t.object)
        for t in result.triples
        if t.predicate == "instantiates"
    }
    assert ("my_mod", "instantiates", "bar") in instantiates
    assert ("my_mod", "instantiates", "baz") in instantiates


def test_contains_edges_link_module_to_children() -> None:
    parser = _make_parser()
    result = parser.extract(SIMPLE_MODULE, source="test.sv")
    contains = {
        (t.subject, t.object) for t in result.triples if t.predicate == "contains"
    }
    assert ("my_mod", "my_mod.clk") in contains
    assert ("my_mod", "my_mod.W") in contains
    assert ("my_mod", "my_mod.s") in contains
    assert ("my_mod", "my_mod.u_bar") in contains


def test_extractor_source_is_sv_parser() -> None:
    parser = _make_parser()
    result = parser.extract(SIMPLE_MODULE, source="test.sv")
    for e in result.entities:
        assert "sv_parser" in e.extractor_source
    for t in result.triples:
        assert t.extractor_source == "sv_parser"


def test_multiple_top_level_decls() -> None:
    """Package + interface + multiple modules in one file are all surfaced."""
    text = """
package mypkg;
  parameter int X = 1;
endpackage

interface my_if;
  logic ready;
endinterface

module foo; endmodule
module bar; endmodule
"""
    parser = _make_parser()
    result = parser.extract(text, source="multi.sv")
    by_type: dict[str, set[str]] = {}
    for e in result.entities:
        by_type.setdefault(e.type, set()).add(e.name)
    assert "mypkg" in by_type.get("Package", set())
    assert "my_if" in by_type.get("Interface", set())
    assert "foo" in by_type.get("RTL_Module", set())
    assert "bar" in by_type.get("RTL_Module", set())


def test_package_import_emits_depends_on() -> None:
    text = """
module m;
  import mypkg::*;
endmodule
"""
    parser = _make_parser()
    result = parser.extract(text, source="m.sv")
    deps = [t for t in result.triples if t.predicate == "depends_on"]
    assert any(t.subject == "m" and t.object == "mypkg" for t in deps), deps


def test_extract_entities_protocol() -> None:
    parser = _make_parser()
    names = parser.extract_entities(SIMPLE_MODULE)
    assert "my_mod" in names
    assert "my_mod.clk" in names


def test_extract_relations_protocol() -> None:
    parser = _make_parser()
    triples = parser.extract_relations(SIMPLE_MODULE, known_entities=set())
    assert any(
        t.subject == "my_mod" and t.predicate == "contains" for t in triples
    )


# -----------------------------------------------------------------------------
# Round-trip integration test — extractor -> backend -> get_outgoing_edges
# -----------------------------------------------------------------------------


def test_roundtrip_contains_edges_survive_networkx_backend() -> None:
    """Drive extracted entities + triples through NetworkXBackend and assert
    that ``contains`` edges from the module to its children survive storage,
    keep their predicate, and are returned by ``get_outgoing_edges``.

    This test exists per the project's integration-test convention (see the
    file-level @summary). It catches storage-layer regressions of the kind
    that masked the connects_to/drives shadowing bug.
    """
    parser = _make_parser()
    backend = NetworkXBackend()
    result = parser.extract(SIMPLE_MODULE, source="test.sv")
    backend.upsert_entities(result.entities)
    backend.upsert_triples(result.triples)

    out = backend.get_outgoing_edges("my_mod")
    contains_targets = {
        t.object for t in out if t.predicate == "contains"
    }
    # All five categories of children must round-trip.
    assert "my_mod.clk" in contains_targets       # Port
    assert "my_mod.W" in contains_targets         # Parameter
    assert "my_mod.s" in contains_targets         # Signal
    assert "my_mod.u_bar" in contains_targets     # Instance

    # And the directional 'instantiates' edge must survive.
    instantiates_targets = {
        t.object for t in out if t.predicate == "instantiates"
    }
    assert "bar" in instantiates_targets
    assert "baz" in instantiates_targets
