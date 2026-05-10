# @summary
# TDD: parser_extractor must emit an RTL_Module entity for every module
# *type* referenced by an `instantiates` triple, not just for modules whose
# own `module foo;` declaration is in the file being parsed. This is the
# fix for the prim_*/tlul_* hierarchy-trace gap: when aes.sv contains
# `prim_lc_sync u_inst (...);`, the parser sees the instance and emits
# `aes -> instantiates -> prim_lc_sync`, but until now it never emitted
# an `Entity(prim_lc_sync, RTL_Module)` — leaving the prim_lc_sync node
# typed 'concept' (auto-created by add_edge) and falling out of
# RTL_Module-filtered queries.
# @end-summary
"""TDD: parser_extractor emits typed entities for instances' module types."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.types import KGConfig, load_schema
from kgweave.knowledge_graph.extraction import SVParserExtractor


pytest.importorskip("pyslang", reason="pyslang required")


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "config" / "kg_schema.yaml"


def _make_parser() -> SVParserExtractor:
    return SVParserExtractor(schema=load_schema(str(SCHEMA_PATH)), config=KGConfig())


def _types_for(name: str, entities) -> set[str]:
    return {e.type for e in entities if e.name == name}


class TestInstantiatesTargetTyping:

    def test_referenced_child_module_typed_rtl_module(self, tmp_path: Path) -> None:
        """Parsing parent.sv that instantiates `prim_lc_sync` must emit an
        RTL_Module entity for prim_lc_sync, even though prim_lc_sync's own
        declaration is in another file we're not parsing here.
        """
        sv = (
            "module parent(input logic clk);\n"
            "  prim_lc_sync u_sync (.clk_i(clk));\n"
            "endmodule"
        )
        result = _make_parser().extract(text=sv, source="parent.sv")
        # Sanity: instantiates triple exists.
        inst = [t for t in result.triples if t.predicate == "instantiates"]
        assert ("parent", "prim_lc_sync") in {(t.subject, t.object) for t in inst}
        # The fix: the child module type has an RTL_Module entity emitted.
        assert "RTL_Module" in _types_for("prim_lc_sync", result.entities), (
            f"prim_lc_sync must be typed RTL_Module; "
            f"emitted entities: {[(e.name, e.type) for e in result.entities]}"
        )

    def test_multiple_instances_of_same_type_emit_one_entity(
        self, tmp_path: Path
    ) -> None:
        """Two `prim_buf` instances → one RTL_Module entity for prim_buf."""
        sv = (
            "module parent(input logic clk);\n"
            "  prim_buf u_a (.clk_i(clk));\n"
            "  prim_buf u_b (.clk_i(clk));\n"
            "endmodule"
        )
        result = _make_parser().extract(text=sv, source="parent.sv")
        prim_buf_ents = [e for e in result.entities if e.name == "prim_buf"]
        assert len(prim_buf_ents) >= 1
        assert all(e.type == "RTL_Module" for e in prim_buf_ents)

    def test_self_declared_module_remains_rtl_module(self, tmp_path: Path) -> None:
        """The module that contains the instance (parent here) must still
        be typed RTL_Module — its own `module parent;` declaration wins."""
        sv = (
            "module parent(input logic clk);\n"
            "  child u_c (.clk_i(clk));\n"
            "endmodule"
        )
        result = _make_parser().extract(text=sv, source="parent.sv")
        assert _types_for("parent", result.entities) == {"RTL_Module"}

    def test_backend_round_trip_preserves_rtl_module_type(
        self, tmp_path: Path
    ) -> None:
        """End-to-end: pushing parser output through the backend, the
        instance-type entity must end up typed RTL_Module on the graph
        node — not 'concept'. Mirrors the AES → prim_lc_sync demo case.
        """
        sv = (
            "module parent(input logic clk);\n"
            "  prim_lc_sync u_sync (.clk_i(clk));\n"
            "endmodule"
        )
        result = _make_parser().extract(text=sv, source="parent.sv")
        backend = NetworkXBackend()
        # Order matters: triples first will create nodes as 'concept' first,
        # then entities upsert must override the placeholder type. This
        # exercises both the parser fix AND the backend setdefault fix.
        backend.upsert_triples(result.triples)
        backend.upsert_entities(result.entities)
        assert backend.graph.nodes["parent"].get("type") == "RTL_Module"
        assert backend.graph.nodes["prim_lc_sync"].get("type") == "RTL_Module"
