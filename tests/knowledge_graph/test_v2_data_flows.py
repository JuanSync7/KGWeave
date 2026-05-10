# @summary
# Wave 2 / track E — V2 unified `data_flows` predicate.
# Verifies that the unified `data_flows` edge dual-emits alongside legacy
# `drives` (port-instance binding) and `drives_signal` (intra-module),
# carries the right `flow_kind` attribute, infers port direction
# correctly (port_in/port_out/inout-both), and that BFS via
# `trace_signal` traces a signal cleanly across module boundaries.
# @end-summary
"""Tests for V2 unified ``data_flows`` predicate (Wave 2 / track E).

Contract under test (see ``docs/v2_dataflow_schema.md``
§ "Cross-module port unification" and § "Schema migration"):

* Every port-instance binding emitted as ``drives`` by
  ``SlangHierarchyAnalyzer`` is dual-emitted as ``data_flows`` with
  ``flow_kind="port_in"`` (parent net -> child input port) or
  ``flow_kind="port_out"`` (child output port -> parent net). ``inout``
  ports emit both directions.
* Every intra-module RHS->LHS edge emitted as ``drives_signal`` by
  ``SVDataflowExtractor`` is dual-emitted as ``data_flows`` with
  ``flow_kind="intra"``.
* ``data_flows`` triples carry ``layer="slang"``.
* ``trace_signal(backend, source)`` BFS walks across module boundaries
  using only the unified predicate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Set, Tuple

import pytest

pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Triple
from kgweave.knowledge_graph.extraction import (
    SlangHierarchyAnalyzer,
    SVDataflowExtractor,
)
from kgweave.knowledge_graph.queries import trace_signal


# ---------------------------------------------------------------------------
# Fixture: 3-module hierarchy (parent -> mid -> child) threading one signal.
# ---------------------------------------------------------------------------

THREE_MODULE_FIXTURE = """\
module child(
    input  logic in_a,
    output logic out_z,
    inout  wire  bidir_b
);
  assign out_z = in_a;
endmodule

module mid(
    input  logic in_a,
    output logic out_z,
    inout  wire  bidir_b
);
  child u_child(.in_a(in_a), .out_z(out_z), .bidir_b(bidir_b));
endmodule

module parent_mod(
    input  logic in_a,
    output logic out_z,
    inout  wire  bidir_b
);
  mid u_mid(.in_a(in_a), .out_z(out_z), .bidir_b(bidir_b));
endmodule
"""


def _build_filelist(tmp_path: Path, files: list[tuple[str, str]]) -> Path:
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files:
        (src_dir / name).write_text(text)
    fl = tmp_path / "files.f"
    fl.write_text("\n".join(str(src_dir / name) for name, _ in files) + "\n")
    return fl


def _run_slang(filelist: Path, top: str = "parent_mod"):
    backend = NetworkXBackend()
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(filelist),
        backend=backend,
        top_module=top,
    )
    result = analyzer.analyze_full()
    # Push the slang result into the backend so the BFS query helpers can
    # walk it. The analyzer returns triples/entities but does not auto-
    # upsert (the production flow has an outer driver doing this).
    if result.entities:
        backend.upsert_entities(result.entities)
    if result.triples:
        backend.upsert_triples(result.triples)
    return result, backend


def _pairs(triples, predicate: str) -> Set[Tuple[str, str]]:
    return {(t.subject, t.object) for t in triples if t.predicate == predicate}


def _data_flows(triples) -> list[Triple]:
    return [t for t in triples if t.predicate == "data_flows"]


# ---------------------------------------------------------------------------
# Cycle 1 — every legacy `drives` port-binding edge has a `data_flows` twin
# ---------------------------------------------------------------------------


def test_port_bindings_dual_emit_data_flows(tmp_path: Path) -> None:
    fl = _build_filelist(tmp_path, [("hier.sv", THREE_MODULE_FIXTURE)])
    result, _backend = _run_slang(fl)

    drives_pairs = _pairs(result.triples, "drives")
    df_pairs = _pairs(result.triples, "data_flows")

    # Every `drives` triple must have a matching (subject, object) in
    # `data_flows`. (data_flows is a superset because it also covers intra-
    # module dataflow that `drives` does not.)
    missing = drives_pairs - df_pairs
    assert not missing, f"data_flows missing dual-emit for: {sorted(missing)}"


def test_data_flows_layer_is_slang(tmp_path: Path) -> None:
    fl = _build_filelist(tmp_path, [("hier.sv", THREE_MODULE_FIXTURE)])
    result, _backend = _run_slang(fl)
    dfs = _data_flows(result.triples)
    assert dfs, "expected at least one data_flows triple"
    bad = [t for t in dfs if t.layer != "slang"]
    assert not bad, f"data_flows triples must carry layer='slang': {bad[:3]}"


# ---------------------------------------------------------------------------
# Cycle 2 — direction inference: input -> port_in, output -> port_out,
#                                 inout -> both
# ---------------------------------------------------------------------------


def test_input_port_emits_flow_kind_port_in(tmp_path: Path) -> None:
    fl = _build_filelist(tmp_path, [("hier.sv", THREE_MODULE_FIXTURE)])
    result, _backend = _run_slang(fl)
    # parent.in_a -> parent.u_mid.in_a binding: parent net drives child input.
    matches = [
        t for t in _data_flows(result.triples)
        if t.subject == "parent_mod.in_a"
        and t.object == "parent_mod.u_mid.in_a"
    ]
    assert matches, "missing data_flows for parent in_a -> u_mid.in_a binding"
    assert all(t.attributes.get("flow_kind") == "port_in" for t in matches), (
        f"input port binding must have flow_kind=port_in, got: "
        f"{[t.attributes for t in matches]}"
    )


def test_output_port_emits_flow_kind_port_out(tmp_path: Path) -> None:
    fl = _build_filelist(tmp_path, [("hier.sv", THREE_MODULE_FIXTURE)])
    result, _backend = _run_slang(fl)
    # parent.u_mid.out_z -> parent.out_z: child output drives parent net.
    matches = [
        t for t in _data_flows(result.triples)
        if t.subject == "parent_mod.u_mid.out_z"
        and t.object == "parent_mod.out_z"
    ]
    assert matches, "missing data_flows for u_mid.out_z -> parent out_z binding"
    assert all(t.attributes.get("flow_kind") == "port_out" for t in matches), (
        f"output port binding must have flow_kind=port_out, got: "
        f"{[t.attributes for t in matches]}"
    )


def test_inout_port_emits_both_directions(tmp_path: Path) -> None:
    fl = _build_filelist(tmp_path, [("hier.sv", THREE_MODULE_FIXTURE)])
    result, _backend = _run_slang(fl)
    dfs = _data_flows(result.triples)
    # An inout binding parent.bidir_b <-> parent.u_mid.bidir_b should
    # produce two data_flows triples: one port_in, one port_out.
    parent = "parent_mod.bidir_b"
    child = "parent_mod.u_mid.bidir_b"
    in_dir = [t for t in dfs if t.subject == parent and t.object == child]
    out_dir = [t for t in dfs if t.subject == child and t.object == parent]
    assert in_dir, "inout binding missing parent->child direction"
    assert out_dir, "inout binding missing child->parent direction"
    assert any(t.attributes.get("flow_kind") == "port_in" for t in in_dir)
    assert any(t.attributes.get("flow_kind") == "port_out" for t in out_dir)


# ---------------------------------------------------------------------------
# Cycle 3 — intra-module dataflow dual-emits data_flows(flow_kind=intra)
# ---------------------------------------------------------------------------


def test_intra_module_drives_signal_dual_emits_data_flows() -> None:
    src = """
    module m(input logic a, output logic y);
      assign y = a;
    endmodule
    """
    # Build the known-signals table the v1 way.
    from kgweave.knowledge_graph.extraction import SVParserExtractor
    from kgweave.knowledge_graph.common import KGConfig, load_schema

    schema_path = (
        Path(__file__).resolve().parents[2] / "config" / "kg_schema.yaml"
    )
    schema = load_schema(str(schema_path))
    cfg = KGConfig()
    parser = SVParserExtractor(schema=schema, config=cfg)
    parser_res = parser.extract(src)
    table: dict[str, set[str]] = {}
    for ent in parser_res.entities:
        if ent.type == "RTL_Module":
            table.setdefault(ent.name, set())
        elif "." in ent.name and ent.type in ("Port", "Signal"):
            mod, sig = ent.name.split(".", 1)
            table.setdefault(mod, set()).add(sig)

    extractor = SVDataflowExtractor(known_module_signals=table)
    res = extractor.extract(text=src, source="test.sv")

    drives_signal_pairs = _pairs(res.triples, "drives_signal")
    df_pairs = _pairs(res.triples, "data_flows")
    assert ("m.a", "m.y") in drives_signal_pairs
    assert ("m.a", "m.y") in df_pairs, "intra-module data_flows missing"

    # All intra-module data_flows triples must carry flow_kind=intra and
    # layer=slang.
    intras = [t for t in res.triples if t.predicate == "data_flows"]
    assert intras
    for t in intras:
        assert t.attributes.get("flow_kind") == "intra", (
            f"intra-module data_flows must have flow_kind=intra: {t}"
        )
        assert t.layer == "slang"


# ---------------------------------------------------------------------------
# Cycle 4 — trace_signal BFS hops cleanly across module boundaries.
# ---------------------------------------------------------------------------


def test_trace_signal_crosses_module_boundaries(tmp_path: Path) -> None:
    fl = _build_filelist(tmp_path, [("hier.sv", THREE_MODULE_FIXTURE)])
    _result, backend = _run_slang(fl)

    paths = trace_signal(backend, "parent_mod.in_a", max_hops=20)
    reached = {p[-1] for p in paths}

    # The seed must thread parent -> mid instance -> child instance via
    # the unified predicate without falling back to legacy edges.
    assert "parent_mod.u_mid.in_a" in reached, (
        f"BFS did not cross parent->mid boundary; reached={sorted(reached)}"
    )
    assert "parent_mod.u_mid.u_child.in_a" in reached, (
        f"BFS did not cross mid->child boundary; reached={sorted(reached)}"
    )


def test_trace_signal_returns_empty_for_unknown_source(tmp_path: Path) -> None:
    fl = _build_filelist(tmp_path, [("hier.sv", THREE_MODULE_FIXTURE)])
    _result, backend = _run_slang(fl)
    assert trace_signal(backend, "no_such_node") == []


def test_trace_signal_respects_max_hops(tmp_path: Path) -> None:
    fl = _build_filelist(tmp_path, [("hier.sv", THREE_MODULE_FIXTURE)])
    _result, backend = _run_slang(fl)

    # max_hops=0 returns just the seed path.
    paths_0 = trace_signal(backend, "parent_mod.in_a", max_hops=0)
    assert paths_0 == [["parent_mod.in_a"]]

    # max_hops=1 reaches at most one hop away.
    paths_1 = trace_signal(backend, "parent_mod.in_a", max_hops=1)
    for p in paths_1:
        assert len(p) <= 2, f"max_hops=1 violated by path {p}"
