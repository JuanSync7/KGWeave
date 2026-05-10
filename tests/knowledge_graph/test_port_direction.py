"""Tests for the Port direction attribute feature.

Verifies that:
* ``Entity.port_direction`` is a recognized schema field (default ``None``).
* ``NetworkXBackend.add_node`` / ``upsert_entities`` round-trips the value.
* The slang extractor emits ``port_direction`` for input/output/inout ports
  (and leaves it ``None`` for ``ref`` or unknown).
* The parser extractor either emits direction or documents why it cannot.
* The ``ports_by_direction`` query helper filters and strips the prefix.
* The query helper is exported from the public facade.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Entity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_filelist(tmp_path: Path, files: Dict[str, str]) -> Path:
    paths = []
    for name, content in files.items():
        p = tmp_path / name
        p.write_text(content)
        paths.append(p.name)
    fl = tmp_path / "files.f"
    fl.write_text("\n".join(paths) + "\n")
    return fl


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestEntitySchema:
    def test_entity_default_port_direction_is_none(self) -> None:
        e = Entity(name="foo.clk", type="Port")
        assert getattr(e, "port_direction", "MISSING") is None

    def test_entity_can_set_port_direction_input(self) -> None:
        e = Entity(name="foo.clk", type="Port", port_direction="input")
        assert e.port_direction == "input"

    def test_entity_can_set_port_direction_output_inout(self) -> None:
        e_out = Entity(name="foo.q", type="Port", port_direction="output")
        e_io = Entity(name="foo.io", type="Port", port_direction="inout")
        assert e_out.port_direction == "output"
        assert e_io.port_direction == "inout"


# ---------------------------------------------------------------------------
# Backend round-trip
# ---------------------------------------------------------------------------


class TestBackendPersistence:
    def test_backend_persists_port_direction_on_node(self) -> None:
        backend = NetworkXBackend()
        backend.upsert_entities([
            Entity(
                name="foo.clk",
                type="Port",
                sources=["t.sv"],
                port_direction="input",
            )
        ])
        data = backend.graph.nodes["foo.clk"]
        assert data.get("port_direction") == "input"

    def test_backend_add_node_explicit_direction(self) -> None:
        backend = NetworkXBackend()
        backend.add_node(
            name="foo.q",
            type="Port",
            source="t.sv",
            port_direction="output",
        )
        assert backend.graph.nodes["foo.q"].get("port_direction") == "output"

    def test_backend_does_not_clobber_existing_direction_with_none(self) -> None:
        backend = NetworkXBackend()
        backend.add_node(
            name="foo.io", type="Port", source="t.sv", port_direction="inout",
        )
        # Re-upsert with no direction — must not erase the prior value.
        backend.add_node(name="foo.io", type="Port", source="t.sv")
        assert backend.graph.nodes["foo.io"].get("port_direction") == "inout"


# ---------------------------------------------------------------------------
# Slang extractor
# ---------------------------------------------------------------------------


class TestSlangPortDirection:
    def test_slang_extractor_emits_input_output_port_direction(
        self, tmp_path: Path
    ) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "foo.sv": (
                "module foo(input logic clk, output logic dout);\n"
                "endmodule\n"
            ),
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="foo",
        )
        result = analyzer.analyze_full()
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        clk = backend.graph.nodes.get("foo.clk", {})
        dout = backend.graph.nodes.get("foo.dout", {})
        assert clk.get("port_direction") == "input", clk
        assert dout.get("port_direction") == "output", dout

    def test_slang_extractor_emits_inout_port_direction(
        self, tmp_path: Path
    ) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "bar.sv": (
                "module bar(inout wire data_io);\n"
                "endmodule\n"
            ),
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="bar",
        )
        result = analyzer.analyze_full()
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        node = backend.graph.nodes.get("bar.data_io", {})
        assert node.get("port_direction") == "inout", node

    def test_slang_extractor_omits_direction_for_ref_or_unknown(
        self, tmp_path: Path
    ) -> None:
        """A function with a ref arg shouldn't surface as a Port with a direction.

        pyslang typically only models module ports as ``SymbolKind.Port``;
        ``ref`` arguments appear on functions/tasks and aren't module ports.
        We just assert the extractor does not crash and that any Port nodes
        emitted carry one of the three valid directions (or None).
        """
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "baz.sv": (
                "module baz(input logic a);\n"
                "  function void f(ref int x); x = 1; endfunction\n"
                "endmodule\n"
            ),
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="baz",
        )
        result = analyzer.analyze_full()
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        for name, data in backend.graph.nodes(data=True):
            if data.get("type") == "Port":
                assert data.get("port_direction") in {
                    "input", "output", "inout", None,
                }, (name, data)


# ---------------------------------------------------------------------------
# Parser extractor (best-effort)
# ---------------------------------------------------------------------------


class TestParserPortDirection:
    def test_parser_extractor_port_direction_or_documented_none(
        self, tmp_path: Path
    ) -> None:
        from kgweave.knowledge_graph.common.types import KGConfig, load_schema
        from kgweave.knowledge_graph.extraction import SVParserExtractor

        sv = tmp_path / "bar.sv"
        sv.write_text(
            "module bar(input logic clk, output logic q);\n"
            "endmodule\n"
        )
        schema_path = Path(__file__).resolve().parents[2] / "config" / "kg_schema.yaml"
        ext = SVParserExtractor(schema=load_schema(str(schema_path)), config=KGConfig())
        result = ext.extract(sv.read_text(), source=str(sv))
        ports = [e for e in result.entities if e.type == "Port"]
        assert ports, "parser_extractor must emit Port entities"
        # Either parser emits direction (preferred) OR all Port entities
        # have port_direction == None (documented limitation; slang dominates).
        directions = {e.port_direction for e in ports}
        if directions == {None}:
            # Documented fallback path — fine; slang fills these in later.
            return
        # Otherwise: at least one Port carries a recognized direction.
        assert directions & {"input", "output", "inout"}, directions


# ---------------------------------------------------------------------------
# Query helper
# ---------------------------------------------------------------------------


class TestPortsByDirectionQuery:
    def _backend_with_ports(self) -> NetworkXBackend:
        b = NetworkXBackend()
        b.upsert_entities([
            Entity(name="foo.clk", type="Port", port_direction="input"),
            Entity(name="foo.rst_n", type="Port", port_direction="input"),
            Entity(name="foo.q", type="Port", port_direction="output"),
            Entity(name="foo.io", type="Port", port_direction="inout"),
            Entity(name="foo.unknown", type="Port"),
            # Different module (must not leak).
            Entity(name="bar.clk", type="Port", port_direction="input"),
            # Same prefix but different type (must not match).
            Entity(name="foo.r", type="Signal", port_direction=None),
        ])
        return b

    def test_ports_by_direction_query_filters_correctly(self) -> None:
        from kgweave.knowledge_graph import ports_by_direction

        b = self._backend_with_ports()
        inputs = ports_by_direction(b, "foo", "input")
        assert inputs == ["clk", "rst_n"]
        outs = ports_by_direction(b, "foo", "output")
        assert outs == ["q"]
        ios = ports_by_direction(b, "foo", "inout")
        assert ios == ["io"]

    def test_ports_by_direction_query_strips_module_prefix(self) -> None:
        from kgweave.knowledge_graph import ports_by_direction

        b = self._backend_with_ports()
        result = ports_by_direction(b, "foo", "input")
        assert all("." not in n for n in result), result
        assert result == sorted(result)


class TestFacadeExports:
    def test_facade_exports_ports_by_direction(self) -> None:
        import kgweave.knowledge_graph as kg

        assert hasattr(kg, "ports_by_direction")
        assert "ports_by_direction" in kg.__all__


# ---------------------------------------------------------------------------
# End-to-end demo sanity (skipped if demo data unavailable)
# ---------------------------------------------------------------------------


class TestFullDemoAssertion:
    def test_full_demo_assertion(self, tmp_path: Path) -> None:
        """Light end-to-end: small inline RTL with known direction set."""
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "demo.sv": (
                "module demo(\n"
                "  input  logic clk,\n"
                "  input  logic rst_n,\n"
                "  output logic [7:0] dout,\n"
                "  inout  wire        sda\n"
                ");\n"
                "endmodule\n"
            ),
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="demo",
        )
        result = analyzer.analyze_full()
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        from kgweave.knowledge_graph import ports_by_direction

        assert ports_by_direction(backend, "demo", "input") == ["clk", "rst_n"]
        assert ports_by_direction(backend, "demo", "output") == ["dout"]
        assert ports_by_direction(backend, "demo", "inout") == ["sda"]
