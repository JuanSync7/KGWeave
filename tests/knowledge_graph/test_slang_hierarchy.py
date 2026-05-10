# @summary
# TDD: SystemVerilog hierarchy + connectivity extraction via pyslang.
# Replaces pyverilog-based sv_connectivity. Validates that the slang-based
# analyzer emits the canonical hierarchy edges (instantiates, instance_of,
# contains, part_of) plus connects_to with proper elaboration (parameter
# resolution, generate expansion, hierarchical paths).
# @end-summary
"""Tests for SlangHierarchyAnalyzer (pyslang-backed SV elaboration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.common import Triple
from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _write_filelist(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write SV files + a .f filelist; return the filelist path."""
    paths = []
    for name, content in files.items():
        p = tmp_path / name
        p.write_text(content)
        paths.append(p.name)
    fl = tmp_path / "files.f"
    fl.write_text("\n".join(paths) + "\n")
    return fl


def _triples_by_predicate(triples: list[Triple], pred: str) -> list[Triple]:
    return [t for t in triples if t.predicate == pred]


# -----------------------------------------------------------------------------
# Module exists / instantiable
# -----------------------------------------------------------------------------


class TestSlangAnalyzerImport:
    def test_can_import_slang_analyzer(self) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer  # noqa: F401

    def test_pyverilog_path_is_removed(self) -> None:
        # Sanity: the new module should not pull in pyverilog.
        import kgweave.knowledge_graph.extraction.sv_connectivity as mod
        src = Path(mod.__file__).read_text()
        assert "pyverilog" not in src.lower(), (
            "sv_connectivity must no longer reference pyverilog after slang swap"
        )


# -----------------------------------------------------------------------------
# Single module: contains edges (ports, signals, parameters)
# -----------------------------------------------------------------------------


class TestSingleModuleHierarchy:
    def test_module_contains_ports(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "leaf.sv": """
            module leaf(input logic clk, input logic rst_n, output logic q);
              logic r;
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="leaf",
        )
        result = analyzer.analyze_full()
        triples = result.triples

        contains = _triples_by_predicate(triples, "contains")
        contains_targets = {t.object for t in contains if t.subject == "leaf"}
        assert "leaf.clk" in contains_targets
        assert "leaf.rst_n" in contains_targets
        assert "leaf.q" in contains_targets

    def test_module_contains_signals(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "leaf.sv": """
            module leaf(input logic clk);
              logic r;
              logic q;
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="leaf",
        )
        result = analyzer.analyze_full()
        contains = _triples_by_predicate(result.triples, "contains")
        targets = {t.object for t in contains}
        assert "leaf.r" in targets
        assert "leaf.q" in targets


# -----------------------------------------------------------------------------
# Hierarchy: instantiates + instance_of + part_of
# -----------------------------------------------------------------------------


class TestHierarchyEdges:
    def test_parent_instantiates_child(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "child.sv": """
            module child(input logic clk, output logic q);
            endmodule
            """,
            "parent.sv": """
            module parent(input logic clk);
              logic w;
              child u_c1 (.clk(clk), .q(w));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        instantiates = _triples_by_predicate(result.triples, "instantiates")
        # parent module instantiates child module (definition-level)
        pairs = {(t.subject, t.object) for t in instantiates}
        assert ("parent", "child") in pairs

    def test_instance_is_instance_of_module(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "child.sv": """
            module child(input logic clk);
            endmodule
            """,
            "parent.sv": """
            module parent(input logic clk);
              child u_c1 (.clk(clk));
              child u_c2 (.clk(clk));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        instance_of = _triples_by_predicate(result.triples, "instance_of")
        pairs = {(t.subject, t.object) for t in instance_of}
        # Hierarchical instance paths point back to the module definition.
        assert ("parent.u_c1", "child") in pairs
        assert ("parent.u_c2", "child") in pairs

    def test_part_of_links_child_to_parent_instance(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "leaf.sv": """
            module leaf(input logic clk);
            endmodule
            """,
            "mid.sv": """
            module mid(input logic clk);
              leaf u_leaf (.clk(clk));
            endmodule
            """,
            "top.sv": """
            module top(input logic clk);
              mid u_mid (.clk(clk));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="top",
        )
        result = analyzer.analyze_full()
        part_of = _triples_by_predicate(result.triples, "part_of")
        pairs = {(t.subject, t.object) for t in part_of}
        # Nested instance points to its enclosing instance via part_of.
        assert ("top.u_mid.u_leaf", "top.u_mid") in pairs
        assert ("top.u_mid", "top") in pairs


# -----------------------------------------------------------------------------
# Connectivity: connects_to with elaborated paths
# -----------------------------------------------------------------------------


class TestConnectivity:
    def test_port_connectivity_emits_drives(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "child.sv": """
            module child(input logic clk_i, output logic q_o);
            endmodule
            """,
            "parent.sv": """
            module parent(input logic clk);
              logic w;
              child u_c (.clk_i(clk), .q_o(w));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        drives = _triples_by_predicate(result.triples, "drives")
        pairs = {(t.subject, t.object) for t in drives}
        assert any(
            "u_c.clk_i" in s or "u_c.clk_i" in o for s, o in pairs
        ), f"Expected u_c.clk_i in {pairs}"
        assert any(
            "u_c.q_o" in s or "u_c.q_o" in o for s, o in pairs
        ), f"Expected u_c.q_o in {pairs}"


# -----------------------------------------------------------------------------
# Provenance: extractor_source set so backend resolves confidence to slang prior
# -----------------------------------------------------------------------------


class TestSlangProvenance:
    def test_triples_carry_slang_extractor_source(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "leaf.sv": """
            module leaf(input logic clk);
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="leaf",
        )
        result = analyzer.analyze_full()
        assert result.triples, "expected at least one triple"
        for t in result.triples:
            assert t.extractor_source == "slang", (
                f"triple {t.subject} {t.predicate} {t.object} lacked slang source"
            )

    def test_backend_resolves_slang_confidence_to_1_0(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "child.sv": """
            module child(input logic clk);
            endmodule
            """,
            "parent.sv": """
            module parent(input logic clk);
              child u_c (.clk(clk));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        backend.upsert_triples(result.triples)
        # Verify at least one slang edge persisted with confidence=1.0
        any_edge_checked = False
        for u, v, data in backend.graph.edges(data=True):
            if data.get("extractor_source") == "slang" or "slang" in str(data):
                pass
            any_edge_checked = True
            assert data.get("confidence", 0.0) == pytest.approx(1.0)
        assert any_edge_checked


# -----------------------------------------------------------------------------
# Directional connectivity: drives edges (Tier 1 #1)
# -----------------------------------------------------------------------------


class TestDrivesEdges:
    def test_drives_edge_for_output_port(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "child.sv": """
            module child(output logic q_o);
            endmodule
            """,
            "parent.sv": """
            module parent;
              logic w;
              child u_c (.q_o(w));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        drives = _triples_by_predicate(result.triples, "drives")
        pairs = {(t.subject, t.object) for t in drives}
        # Output port: instance port drives external net.
        assert ("parent.u_c.q_o", "parent.w") in pairs, (
            f"Expected output port to drive external net, got {pairs}"
        )

    def test_drives_edge_for_input_port(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "child.sv": """
            module child(input logic clk_i);
            endmodule
            """,
            "parent.sv": """
            module parent(input logic clk);
              child u_c (.clk_i(clk));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        drives = _triples_by_predicate(result.triples, "drives")
        pairs = {(t.subject, t.object) for t in drives}
        # Input port: external net drives instance port.
        assert ("parent.clk", "parent.u_c.clk_i") in pairs, (
            f"Expected external net to drive input port, got {pairs}"
        )

    def test_drives_edge_for_inout_port(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "child.sv": """
            module child(inout wire bidir_io);
            endmodule
            """,
            "parent.sv": """
            module parent;
              wire bus;
              child u_c (.bidir_io(bus));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        drives = _triples_by_predicate(result.triples, "drives")
        pairs = {(t.subject, t.object) for t in drives}
        # Inout: both directions emitted.
        assert ("parent.u_c.bidir_io", "parent.bus") in pairs, (
            f"Expected port -> net for inout, got {pairs}"
        )
        assert ("parent.bus", "parent.u_c.bidir_io") in pairs, (
            f"Expected net -> port for inout, got {pairs}"
        )

    def test_connects_to_no_longer_emitted(self, tmp_path: Path) -> None:
        """connects_to was dropped — DiGraph collapses parallel (subj,obj)
        edges into one record, which silently shadowed the directional
        ``drives`` edges. Only ``drives`` is emitted now."""
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "child.sv": """
            module child(input logic clk_i, output logic q_o);
            endmodule
            """,
            "parent.sv": """
            module parent(input logic clk);
              logic w;
              child u_c (.clk_i(clk), .q_o(w));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        connects = _triples_by_predicate(result.triples, "connects_to")
        assert not connects, "connects_to should no longer be emitted"


# -----------------------------------------------------------------------------
# Parameter value bindings (Tier 1 #2)
# -----------------------------------------------------------------------------


class TestParameterBindings:
    def test_binds_parameter_edge_for_overridden_value(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "regfile.sv": """
            module regfile #(parameter int unsigned NumRegs = 16) (
              input logic clk_i
            );
            endmodule
            """,
            "parent.sv": """
            module parent(input logic clk);
              regfile #(.NumRegs(32)) u_regfile (.clk_i(clk));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        binds = _triples_by_predicate(result.triples, "binds_parameter")
        # Find the NumRegs binding for u_regfile.
        matches = [
            t for t in binds
            if t.subject == "parent.u_regfile" and t.object == "regfile.NumRegs"
        ]
        assert matches, f"Expected binds_parameter from parent.u_regfile -> regfile.NumRegs, got {[(t.subject, t.object) for t in binds]}"
        t = matches[0]
        assert t.evidence_span is not None
        # slang stringifies sized integer constants as e.g. "32'd32"; require
        # the parameter name prefix and the decimal value substring.
        assert t.evidence_span.startswith("NumRegs=") and "32" in t.evidence_span, (
            f"Expected override value 32 in 'NumRegs=...', got {t.evidence_span!r}"
        )
        assert t.extractor_source == "slang"

    def test_binds_parameter_edge_for_default_value(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "regfile.sv": """
            module regfile #(parameter int unsigned NumRegs = 16) (
              input logic clk_i
            );
            endmodule
            """,
            "parent.sv": """
            module parent(input logic clk);
              regfile u_regfile (.clk_i(clk));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="parent",
        )
        result = analyzer.analyze_full()
        binds = _triples_by_predicate(result.triples, "binds_parameter")
        matches = [
            t for t in binds
            if t.subject == "parent.u_regfile" and t.object == "regfile.NumRegs"
        ]
        assert matches, (
            f"Expected default-value binding edge, got {[(t.subject, t.object) for t in binds]}"
        )
        t = matches[0]
        assert t.evidence_span is not None
        # slang stringifies sized integer constants as e.g. "32'd16"; just
        # require the parameter name and the decimal value to appear together.
        assert t.evidence_span.startswith("NumRegs=") and "16" in t.evidence_span, (
            f"Expected default value 16 in 'NumRegs=...', got {t.evidence_span!r}"
        )
        assert t.extractor_source == "slang"


# -----------------------------------------------------------------------------
# Clock / reset domain extraction (Tier 2 #5)
# -----------------------------------------------------------------------------


class TestClockResetDomains:
    def test_clock_domain_entity_emitted(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "leaf.sv": """
            module leaf(input logic clk, output logic q);
              logic r;
              always_ff @(posedge clk) r <= 1;
              assign q = r;
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="leaf",
        )
        result = analyzer.analyze_full()
        clock_entities = [e for e in result.entities if e.type == "ClockDomain"]
        names = {e.name for e in clock_entities}
        assert "clk" in names, f"Expected ClockDomain 'clk' in {names}"

    def test_distinct_clocks_yield_distinct_domains(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "blk_a.sv": """
            module blk_a(input logic clk_a);
              logic r;
              always_ff @(posedge clk_a) r <= 1;
            endmodule
            """,
            "blk_b.sv": """
            module blk_b(input logic clk_b);
              logic r;
              always_ff @(posedge clk_b) r <= 1;
            endmodule
            """,
            "top.sv": """
            module top(input logic clk_a, input logic clk_b);
              blk_a u_a (.clk_a(clk_a));
              blk_b u_b (.clk_b(clk_b));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="top",
        )
        result = analyzer.analyze_full()
        clocks = {e.name for e in result.entities if e.type == "ClockDomain"}
        assert clocks == {"clk_a", "clk_b"}, f"Expected exactly clk_a, clk_b — got {clocks}"

    def test_module_clocked_by_clock_domain(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "leaf.sv": """
            module leaf(input logic clk_main);
              logic r;
              always_ff @(posedge clk_main) r <= 1;
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="leaf",
        )
        result = analyzer.analyze_full()
        # Round-trip via the backend to catch DiGraph-edge-collapse regressions.
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        outgoing = backend.get_outgoing_edges("leaf")
        clocked = [t for t in outgoing if t.predicate == "clocked_by"]
        objs = {t.object for t in clocked}
        assert "clk_main" in objs, (
            f"Expected leaf -clocked_by-> clk_main after round-trip, got {objs}"
        )

    def test_reset_domain_emitted_with_negedge_rst_n(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "leaf.sv": """
            module leaf(input logic clk, input logic rst_n);
              logic r;
              always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) r <= 0;
                else r <= 1;
              end
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="leaf",
        )
        result = analyzer.analyze_full()
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        reset_entities = {e.name for e in result.entities if e.type == "ResetDomain"}
        assert "rst_n" in reset_entities, f"Expected ResetDomain 'rst_n', got {reset_entities}"

        outgoing = backend.get_outgoing_edges("leaf")
        reset_edges = [t for t in outgoing if t.predicate == "reset_by"]
        assert any(t.object == "rst_n" for t in reset_edges), (
            f"Expected leaf -reset_by-> rst_n, got {reset_edges}"
        )
        # The clock should not be misclassified as a reset.
        assert not any(e.name == "clk" and e.type == "ResetDomain" for e in result.entities)

    def test_cdc_two_modules_share_or_split_clocks(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {
            "blk_a.sv": """
            module blk_a(input logic clk_a);
              logic r;
              always_ff @(posedge clk_a) r <= 1;
            endmodule
            """,
            "blk_b.sv": """
            module blk_b(input logic clk_b);
              logic r;
              always_ff @(posedge clk_b) r <= 1;
            endmodule
            """,
            "top.sv": """
            module top(input logic clk_a, input logic clk_b);
              blk_a u_a (.clk_a(clk_a));
              blk_b u_b (.clk_b(clk_b));
            endmodule
            """,
        })
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="top",
        )
        result = analyzer.analyze_full()
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        # Reverse-traverse clocked_by from clk_a — find every module clocked
        # by clk_a. Use the in-edges of the ClockDomain node.
        in_edges = list(backend.graph.in_edges("clk_a", data=True))
        modules_in_clk_a = {
            u for u, _v, d in in_edges if d.get("relation") == "clocked_by"
        }
        assert "blk_a" in modules_in_clk_a, (
            f"Expected blk_a in clk_a domain, got {modules_in_clk_a}"
        )
        assert "blk_b" not in modules_in_clk_a, (
            f"blk_b must NOT be in clk_a domain, got {modules_in_clk_a}"
        )

    def test_no_duplicate_clock_domain_for_repeated_clock(self, tmp_path: Path) -> None:
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        files = {}
        for i in range(5):
            files[f"blk{i}.sv"] = f"""
            module blk{i}(input logic clk_main);
              logic r;
              always_ff @(posedge clk_main) r <= 1;
            endmodule
            """
        files["top.sv"] = """
        module top(input logic clk_main);
          blk0 u0 (.clk_main(clk_main));
          blk1 u1 (.clk_main(clk_main));
          blk2 u2 (.clk_main(clk_main));
          blk3 u3 (.clk_main(clk_main));
          blk4 u4 (.clk_main(clk_main));
        endmodule
        """
        fl = _write_filelist(tmp_path, files)
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="top",
        )
        result = analyzer.analyze_full()
        clock_entities = [e for e in result.entities if e.type == "ClockDomain"]
        clk_main_entities = [e for e in clock_entities if e.name == "clk_main"]
        assert len(clk_main_entities) == 1, (
            f"Expected exactly one ClockDomain 'clk_main', got "
            f"{[e.name for e in clock_entities]}"
        )


# -----------------------------------------------------------------------------
# Concurrent / immediate assertions (Tier 2 #6)
# -----------------------------------------------------------------------------


class TestAssertions:
    """SVA assertion extraction via pyslang's elaborated symbol tree.

    The analyzer surfaces concurrent assertions as ``ProceduralBlock`` symbols
    whose body is ``StatementKind.ConcurrentAssertion``; labels come from the
    preceding sibling ``StatementBlock`` (slang's elaboration of
    ``my_label: assert property (...)``). Property-text identifier scraping
    drives the ``references_signal`` edges.
    """

    _DUT = """
    module dut(input logic clk, input logic req, output logic ack);
      assert property (@(posedge clk) req |-> ##[1:3] ack);
    endmodule
    """

    def _run(self, tmp_path: Path, src: str = None):
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        fl = _write_filelist(tmp_path, {"dut.sv": src or self._DUT})
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module="dut",
        )
        return backend, analyzer.analyze_full()

    def test_concurrent_assert_property_emits_assertion_entity(
        self, tmp_path: Path,
    ) -> None:
        _, result = self._run(tmp_path)
        sva = [e for e in result.entities if e.type == "SVA_Assertion"]
        assert len(sva) >= 1, "expected at least one SVA_Assertion entity"
        # Anonymous assertion → kind embedded in entity name.
        assert any(e.name.startswith("dut.assert") for e in sva), (
            f"expected dut.assert_* entity name, got {[e.name for e in sva]}"
        )

    def test_assertion_has_assertion_edge_from_module(
        self, tmp_path: Path,
    ) -> None:
        _, result = self._run(tmp_path)
        has_assertion = _triples_by_predicate(result.triples, "has_assertion")
        sources = {t.subject for t in has_assertion}
        assert "dut" in sources, (
            f"expected dut --has_assertion--> ..., got {has_assertion}"
        )
        # The object of the edge is the assertion entity name.
        targets = {t.object for t in has_assertion if t.subject == "dut"}
        sva_names = {e.name for e in result.entities if e.type == "SVA_Assertion"}
        assert targets & sva_names, "has_assertion targets must be SVA_Assertion entities"

    def test_assertion_references_signals_in_property(
        self, tmp_path: Path,
    ) -> None:
        # Documents: clock identifier appearing in @(posedge clk) is mapped
        # to the bare ClockDomain entity ``clk`` (no module prefix), matching
        # the existing ``clocked_by`` convention. Plain port refs (req, ack)
        # use the ``dut.<name>`` qualified form.
        _, result = self._run(tmp_path)
        refs = _triples_by_predicate(result.triples, "references_signal")
        targets = {t.object for t in refs}
        assert "dut.req" in targets
        assert "dut.ack" in targets
        assert "clk" in targets, (
            f"expected ClockDomain ref to 'clk', got {targets}"
        )

    def test_assume_and_cover_distinguished_by_kind(
        self, tmp_path: Path,
    ) -> None:
        src = """
        module dut(input logic clk, input logic req, output logic ack);
          assert property (@(posedge clk) req |-> ack);
          assume property (@(posedge clk) req);
          cover  property (@(posedge clk) ack);
        endmodule
        """
        _, result = self._run(tmp_path, src=src)
        sva = [e for e in result.entities if e.type == "SVA_Assertion"]
        assert len(sva) == 3, f"expected 3 SVA_Assertions, got {[e.name for e in sva]}"

        has = _triples_by_predicate(result.triples, "has_assertion")
        kinds = sorted(t.evidence_span for t in has if t.subject == "dut")
        # evidence_span carries ``kind=<assert|assume|cover>``
        assert "kind=assert" in kinds
        assert "kind=assume" in kinds
        assert "kind=cover" in kinds

    def test_named_property_uses_label_in_entity_name(
        self, tmp_path: Path,
    ) -> None:
        # Documents: the chosen entity-name format for labeled assertions is
        # ``{module}.{label}``. A named ``my_label: assert property (...)``
        # elaborates as a sibling StatementBlock(name="my_label") + an
        # anonymous ProceduralBlock, which the analyzer pairs in body order.
        src = """
        module dut(input logic clk, input logic sig);
          my_label: assert property (@(posedge clk) sig);
        endmodule
        """
        _, result = self._run(tmp_path, src=src)
        sva = [e for e in result.entities if e.type == "SVA_Assertion"]
        names = {e.name for e in sva}
        assert "dut.my_label" in names, (
            f"expected dut.my_label, got {names}"
        )

    def test_round_trip_into_networkx_backend(self, tmp_path: Path) -> None:
        """Post-shadowing-bug round-trip integration test.

        Convention (per project mandate): every new extraction must include
        a test that extracts → upserts into NetworkXBackend → queries via
        ``get_outgoing_edges`` and asserts the edges survived storage. This
        guards against the parallel-edge collapse bug where two predicates
        between the same (subject, object) pair silently shadowed one
        another in the underlying DiGraph.
        """
        backend, result = self._run(tmp_path)
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        out = backend.get_outgoing_edges("dut")
        has_assertion = [t for t in out if t.predicate == "has_assertion"]
        assert has_assertion, (
            f"has_assertion edge from 'dut' did not survive backend upsert; "
            f"outgoing edges: {[(t.predicate, t.object) for t in out]}"
        )
        # The targeted SVA_Assertion entity must itself be reachable and
        # carry references_signal edges to the property's signals.
        assertion_name = has_assertion[0].object
        ref_out = backend.get_outgoing_edges(assertion_name)
        ref_targets = {t.object for t in ref_out if t.predicate == "references_signal"}
        assert "dut.req" in ref_targets
        assert "dut.ack" in ref_targets


# -----------------------------------------------------------------------------
# FSM state + transition extraction (Tier 2 #7)
# -----------------------------------------------------------------------------


class TestFSM:
    """FSM extraction via pyslang's elaborated symbol tree.

    The analyzer discovers FSMs by:
      1. Walking module bodies for ``SymbolKind.TypeAlias`` whose target is
         an ``EnumType``.
      2. Finding state-typed Variables (Variable.type.canonicalType is the
         enum).
      3. Choosing the registered state variable (LHS of a non-blocking
         assignment inside ``always_ff``) as the FSM's representative — when
         a module declares both ``cs`` and ``ns`` of the same enum, we treat
         ``cs`` as the FSM (one FSM per enum-type, not two).
      4. Walking ``StatementKind.Case`` statements whose selector is a
         state-typed variable; for each arm, harvesting
         ``(label_enum, rhs_enum)`` pairs from any state-targeting
         ``Assignment`` (handles both ``<=`` in ``always_ff`` and ``=`` in
         ``always_comb``).

    Per project mandate (post-shadowing-bug convention), this class
    includes a round-trip integration test that extracts → upserts into
    NetworkXBackend → queries via ``get_outgoing_edges`` to guard against
    parallel-edge collapse in the underlying DiGraph.
    """

    _DUT = """
    module ctrl(input logic clk, input logic rst_n, input logic go, output logic done);
      typedef enum logic [1:0] { IDLE, RUN, FINISH } state_e;
      state_e cs, ns;
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) cs <= IDLE;
        else        cs <= ns;
      end
      always_comb begin
        ns = cs;
        case (cs)
          IDLE:   if (go)  ns = RUN;
          RUN:             ns = FINISH;
          FINISH:          ns = IDLE;
        endcase
      end
      assign done = (cs == FINISH);
    endmodule
    """

    def _run(self, tmp_path: Path, src: str = None, files: dict = None,
             top: str = "ctrl"):
        from kgweave.knowledge_graph.extraction import SlangHierarchyAnalyzer

        if files is None:
            files = {"ctrl.sv": src or self._DUT}
        fl = _write_filelist(tmp_path, files)
        backend = NetworkXBackend()
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(fl), backend=backend, top_module=top,
        )
        return backend, analyzer.analyze_full()

    def test_simple_fsm_emits_states(self, tmp_path: Path) -> None:
        _, result = self._run(tmp_path)
        states = {e.name for e in result.entities if e.type == "FSM_State"}
        assert "ctrl.IDLE" in states
        assert "ctrl.RUN" in states
        assert "ctrl.FINISH" in states

    def test_fsm_entity_emitted(self, tmp_path: Path) -> None:
        # When a module declares both `cs` and `ns` of the same enum type,
        # the FSM is the registered variable (LHS of NBA in always_ff) — i.e.
        # `cs`. We emit ONE FSM per enum-type, never two.
        _, result = self._run(tmp_path)
        fsms = [e for e in result.entities if e.type == "FSM"]
        names = {e.name for e in fsms}
        # Note: FSM entity is namespaced as ``{module}.fsm_{var}`` to avoid
        # colliding with the signal entity ``{module}.{var}`` (the DiGraph
        # collapses parallel edges between the same (subj,obj) pair).
        assert names == {"ctrl.fsm_cs"}, (
            f"Expected exactly one FSM 'ctrl.fsm_cs' (the NBA-registered var), "
            f"got {names}"
        )

    def test_has_state_edges_link_fsm_to_states(self, tmp_path: Path) -> None:
        _, result = self._run(tmp_path)
        has_state = _triples_by_predicate(result.triples, "has_state")
        from_cs = {t.object for t in has_state if t.subject == "ctrl.fsm_cs"}
        assert from_cs == {"ctrl.IDLE", "ctrl.RUN", "ctrl.FINISH"}, (
            f"Expected ctrl.fsm_cs -has_state-> {{IDLE, RUN, FINISH}}, got {from_cs}"
        )

    def test_transitions_to_edges_capture_case_arms(self, tmp_path: Path) -> None:
        _, result = self._run(tmp_path)
        transitions = _triples_by_predicate(result.triples, "transitions_to")
        pairs = {(t.subject, t.object) for t in transitions}
        assert ("ctrl.IDLE", "ctrl.RUN") in pairs
        assert ("ctrl.RUN", "ctrl.FINISH") in pairs
        assert ("ctrl.FINISH", "ctrl.IDLE") in pairs
        # At least one transition carries non-empty evidence_span
        # mentioning the trigger source state / selector variable.
        assert any(t.evidence_span and "from=" in t.evidence_span for t in transitions), (
            f"Expected evidence_span with 'from=...', got "
            f"{[t.evidence_span for t in transitions]}"
        )

    def test_fsm_in_one_module_does_not_leak_to_another(self, tmp_path: Path) -> None:
        files = {
            "mod_a.sv": """
            module mod_a(input logic clk);
              typedef enum logic [0:0] { IDLE, RUN } state_a_e;
              state_a_e cs_a, ns_a;
              always_ff @(posedge clk) cs_a <= ns_a;
              always_comb begin
                ns_a = cs_a;
                case (cs_a)
                  IDLE: ns_a = RUN;
                  RUN:  ns_a = IDLE;
                endcase
              end
            endmodule
            """,
            "mod_b.sv": """
            module mod_b(input logic clk);
              typedef enum logic [0:0] { IDLE, RUN } state_b_e;
              state_b_e cs_b, ns_b;
              always_ff @(posedge clk) cs_b <= ns_b;
              always_comb begin
                ns_b = cs_b;
                case (cs_b)
                  IDLE: ns_b = RUN;
                  RUN:  ns_b = IDLE;
                endcase
              end
            endmodule
            """,
            "top.sv": """
            module top(input logic clk);
              mod_a u_a (.clk(clk));
              mod_b u_b (.clk(clk));
            endmodule
            """,
        }
        _, result = self._run(tmp_path, files=files, top="top")
        states = {e.name for e in result.entities if e.type == "FSM_State"}
        # Each module's IDLE/RUN gets its own namespaced entity.
        assert "mod_a.IDLE" in states
        assert "mod_a.RUN" in states
        assert "mod_b.IDLE" in states
        assert "mod_b.RUN" in states
        # No collision: there must NOT be a bare/unnamespaced IDLE.
        assert "IDLE" not in states
        assert "RUN" not in states

        # And transitions are properly scoped to each module.
        transitions = {(t.subject, t.object)
                       for t in result.triples if t.predicate == "transitions_to"}
        assert ("mod_a.IDLE", "mod_a.RUN") in transitions
        assert ("mod_b.IDLE", "mod_b.RUN") in transitions
        # Critical: no cross-module edges.
        assert ("mod_a.IDLE", "mod_b.RUN") not in transitions
        assert ("mod_b.IDLE", "mod_a.RUN") not in transitions

    def test_round_trip_into_networkx_backend(self, tmp_path: Path) -> None:
        """Post-shadowing-bug round-trip integration test for FSM edges.

        Extracts → upserts into NetworkXBackend → queries via
        ``get_outgoing_edges`` and asserts the FSM/state edges survived
        storage in the underlying DiGraph.
        """
        backend, result = self._run(tmp_path)
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        # has_fsm: module -> FSM
        out_mod = backend.get_outgoing_edges("ctrl")
        has_fsm = [t for t in out_mod if t.predicate == "has_fsm"]
        assert any(t.object == "ctrl.fsm_cs" for t in has_fsm), (
            f"Expected ctrl --has_fsm--> ctrl.fsm_cs after round-trip, got "
            f"{[(t.predicate, t.object) for t in out_mod]}"
        )

        # has_state: FSM -> each state, queried via the backend.
        out_fsm = backend.get_outgoing_edges("ctrl.fsm_cs")
        has_state_targets = {t.object for t in out_fsm if t.predicate == "has_state"}
        assert {"ctrl.IDLE", "ctrl.RUN", "ctrl.FINISH"}.issubset(has_state_targets), (
            f"Expected has_state edges from ctrl.fsm_cs to all three states "
            f"after round-trip, got {has_state_targets}"
        )

        # transitions_to: state -> next state, queried via backend.
        out_idle = backend.get_outgoing_edges("ctrl.IDLE")
        transitions = [t for t in out_idle if t.predicate == "transitions_to"]
        assert any(t.object == "ctrl.RUN" for t in transitions), (
            f"Expected ctrl.IDLE --transitions_to--> ctrl.RUN after round-trip, "
            f"got {[(t.predicate, t.object) for t in out_idle]}"
        )
