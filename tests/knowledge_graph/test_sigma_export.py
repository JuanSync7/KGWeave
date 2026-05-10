"""Tests for sigma_export Port direction display labels and full-graph
edge export (auto-created node coverage).

Two-part test surface:

1. Port-direction display label: each Port node should expose a
   ``display_type`` attribute on the exported node payload that reads
   ``"Port [In]"``, ``"Port [Out]"``, ``"Port [InOut]"``, or plain
   ``"Port"`` based on the entity's ``port_direction``. The underlying
   ``entityType`` field MUST stay ``"Port"`` (display-only concern).

2. Full-graph edge export: the export must iterate the backend graph's
   full edge set so auto-created signal nodes (created via ``add_edge``
   without a corresponding ``upsert_entities`` call) and their outbound
   edges are NOT lost. Every node in ``backend.graph.nodes`` and every
   edge in ``backend.graph.edges`` must appear in the JSON output.
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
    m = re.search(
        r"const graphData = (\{.*?\});\s*\n\s*// Build graph",
        text,
        re.DOTALL,
    )
    assert m, "Could not find embedded __GRAPH_DATA__ JSON"
    return json.loads(m.group(1))


def _node_attrs(data: dict, key: str) -> dict:
    for n in data["nodes"]:
        if n["key"] == key:
            return n["attributes"]
    raise AssertionError(f"node {key!r} not found in export "
                         f"(found: {[n['key'] for n in data['nodes']]})")


# ---------------------------------------------------------------------------
# Port-direction display label
# ---------------------------------------------------------------------------


def test_port_in_displays_as_port_in_label(tmp_path: Path) -> None:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="dut.clk", type="Port", port_direction="input"),
    ])
    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    attrs = _node_attrs(data, "dut.clk")
    assert attrs["entityType"] == "Port"
    assert attrs["display_type"] == "Port [In]"


def test_port_out_displays_as_port_out_label(tmp_path: Path) -> None:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="dut.dout", type="Port", port_direction="output"),
    ])
    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    attrs = _node_attrs(data, "dut.dout")
    assert attrs["entityType"] == "Port"
    assert attrs["display_type"] == "Port [Out]"


def test_port_inout_displays_as_port_inout_label(tmp_path: Path) -> None:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="dut.io", type="Port", port_direction="inout"),
    ])
    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    attrs = _node_attrs(data, "dut.io")
    assert attrs["entityType"] == "Port"
    assert attrs["display_type"] == "Port [InOut]"


def test_port_no_direction_displays_plain_port(tmp_path: Path) -> None:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="dut.unknown", type="Port", port_direction=None),
    ])
    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    attrs = _node_attrs(data, "dut.unknown")
    assert attrs["entityType"] == "Port"
    assert attrs["display_type"] == "Port"


def test_non_port_entity_unaffected_by_display_label(tmp_path: Path) -> None:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="aes_module", type="RTL_Module"),
        Entity(name="data_bus", type="Signal"),
    ])
    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)

    mod_attrs = _node_attrs(data, "aes_module")
    sig_attrs = _node_attrs(data, "data_bus")

    # entityType still set on non-Port nodes; display_type either matches
    # the entity type verbatim or is omitted — the contract says the
    # decoration is Port-specific. Either way, it must NOT contain a
    # "Port [...]" decoration.
    assert mod_attrs["entityType"] == "RTL_Module"
    assert "[" not in mod_attrs.get("display_type", "RTL_Module")
    assert sig_attrs["entityType"] == "Signal"
    assert "[" not in sig_attrs.get("display_type", "Signal")


# ---------------------------------------------------------------------------
# Full-graph edge export — auto-created signal nodes
# ---------------------------------------------------------------------------


def test_auto_created_signal_node_exported(tmp_path: Path) -> None:
    """A node introduced solely via ``add_edge`` (no upsert_entities call)
    must still appear in the exported nodes list."""
    backend = NetworkXBackend()
    # Push a triple without upserting either endpoint as an Entity.
    backend.add_edge(
        subject="modA.sig_a",
        object="modB.sig_b",
        relation="drives_signal",
        source="parser",
    )

    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    keys = {n["key"] for n in data["nodes"]}
    assert "modA.sig_a" in keys
    assert "modB.sig_b" in keys

    # The single edge must also be exported
    edge_pairs = {(e["source"], e["target"], e["attributes"]["predicate"])
                  for e in data["edges"]}
    assert ("modA.sig_a", "modB.sig_b", "drives_signal") in edge_pairs


def test_auto_created_signal_node_outbound_edges_exported(
    tmp_path: Path,
) -> None:
    """Chain a→b→c via auto-created nodes; both edges and all three
    nodes must be in the output."""
    backend = NetworkXBackend()
    backend.add_edge("a", "b", "drives_signal", source="parser")
    backend.add_edge("b", "c", "drives_signal", source="parser")

    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    keys = {n["key"] for n in data["nodes"]}
    assert {"a", "b", "c"}.issubset(keys), f"missing nodes: {keys}"

    edge_pairs = {(e["source"], e["target"]) for e in data["edges"]}
    assert ("a", "b") in edge_pairs
    assert ("b", "c") in edge_pairs


def test_explicit_entity_still_exported(tmp_path: Path) -> None:
    """Regression: explicitly-upserted entities still appear with their
    attributes intact (entityType, sources)."""
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(
            name="aes_top",
            type="RTL_Module",
            sources=["rtl/aes_top.sv"],
        ),
    ])

    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    attrs = _node_attrs(data, "aes_top")
    assert attrs["entityType"] == "RTL_Module"
    assert "rtl/aes_top.sv" in attrs["sources"]
    assert attrs["mentions"] >= 1


def test_total_edge_count_matches_graph_edge_count(tmp_path: Path) -> None:
    """For a synthetic graph with a known edge count, the number of
    exported edges must equal ``backend.graph.size()`` — no dedup, no
    drops, no double-counting."""
    backend = NetworkXBackend()
    # Mix explicit entities with auto-created edge endpoints.
    backend.upsert_entities([
        Entity(name="m1", type="RTL_Module"),
        Entity(name="m2", type="RTL_Module"),
    ])
    triples = [
        # Explicit edges between explicit entities.
        Triple(subject="m1", predicate="instantiates", object="m2"),
        # Auto-created endpoints — not in entities list.
        Triple(subject="m1.sig_x", predicate="drives_signal",
               object="m2.sig_y"),
        Triple(subject="m2.sig_y", predicate="drives_signal",
               object="m2.sig_z"),
        Triple(subject="m1.sig_p", predicate="drives_signal",
               object="m1.sig_q"),
    ]
    backend.upsert_triples(triples)

    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    assert len(data["edges"]) == backend.graph.size(), (
        f"exported {len(data['edges'])} edges, "
        f"but graph has {backend.graph.size()}"
    )
