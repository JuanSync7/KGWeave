"""Tests for the edge-tooltip surface in the sigma export.

Edge data (predicate, bit-slice, evidence span, source) must round-trip
through the embedded graphData so the JS hover handler can render it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple
from kgweave.knowledge_graph.export import export_html


def _extract_graph_data(html_path: Path) -> dict:
    text = html_path.read_text(encoding="utf-8")
    m = re.search(r"const graphData = (\{.*?\});\s*\n\s*// Build graph",
                  text, re.DOTALL)
    assert m, "Could not find embedded graphData JSON"
    return json.loads(m.group(1))


def _build_backend_with_sliced_reads() -> NetworkXBackend:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="mod.data_o", type="Port"),
        Entity(name="mod.bus", type="Signal"),
    ])
    backend.upsert_triples([
        Triple(
            subject="mod.data_o",
            predicate="reads",
            object="mod.bus",
            source="mod.sv",
            evidence_span="data_o[31:24] = bus[7:0]",
            lhs_slice="[31:24]",
            rhs_slice="[7:0]",
        ),
    ])
    return backend


def test_edge_attributes_include_slice_and_evidence(tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    export_html(backend=_build_backend_with_sliced_reads(), output_path=str(out))

    data = _extract_graph_data(out)
    edges = [e for e in data["edges"] if e["attributes"].get("predicate") == "reads"]
    assert edges, "expected at least one reads edge in graphData"
    a = edges[0]["attributes"]

    assert a["lhs_slice"] == "[31:24]"
    assert a["rhs_slice"] == "[7:0]"
    assert a["evidence_span"] == "data_o[31:24] = bus[7:0]"
    assert a["edgeSource"] == "mod.sv"
    assert a["predicate"] == "reads"


def test_html_has_edge_hover_handler(tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    export_html(backend=_build_backend_with_sliced_reads(), output_path=str(out))
    text = out.read_text(encoding="utf-8")

    assert 'enableEdgeEvents: true' in text, \
        "Sigma renderer must enable edge events for edge tooltips to fire"
    assert 'renderer.on("enterEdge"' in text
    assert 'renderer.on("leaveEdge"' in text
    assert "lhs_slice" in text and "rhs_slice" in text
    assert "evidence_span" in text


def test_non_reads_edges_have_null_slice_attrs(tmp_path: Path) -> None:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="aes", type="RTL_Module"),
        Entity(name="clk_main", type="ClockDomain"),
    ])
    backend.upsert_triples([
        Triple(subject="aes", predicate="clocked_by", object="clk_main",
               source="aes.sv"),
    ])
    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    edges = [e for e in data["edges"]
             if e["attributes"].get("predicate") == "clocked_by"]
    assert edges, "expected the clocked_by edge to be serialized"
    a = edges[0]["attributes"]
    assert a["lhs_slice"] is None
    assert a["rhs_slice"] is None
    assert a["edgeSource"] == "aes.sv"
