"""Tests for the edge-predicate legend section in sigma_export HTML output.

Regression: ``legend.edge_styles`` was emitted in the JSON payload but no
JS-side rendering existed, so edge colours had no key in the legend UI.
"""

from __future__ import annotations

from pathlib import Path

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple
from kgweave.knowledge_graph.export import export_html


def _build_backend() -> NetworkXBackend:
    backend = NetworkXBackend()
    backend.upsert_entities(
        [
            Entity(name="A", type="RTL_Module"),
            Entity(name="B", type="Signal"),
        ]
    )
    backend.upsert_triples(
        [
            Triple(subject="A", predicate="drives", object="B", source="x.sv"),
            Triple(subject="A", predicate="mentions", object="B", source="x.sv"),
        ]
    )
    return backend


def test_edge_predicates_legend_section_rendered(tmp_path: Path):
    backend = _build_backend()
    out = tmp_path / "graph.html"
    export_html(backend, str(out))
    html = out.read_text(encoding="utf-8")

    # The legend now renders predicates grouped by semantic class. Both
    # `drives` (Dataflow) and `mentions` (Reference) are in this fixture,
    # so both class headers must appear.
    assert "Dataflow" in html
    assert "Reference" in html
    # The actually-used predicates appear in the embedded JSON data
    assert "drives" in html
    assert "mentions" in html
    # The JS code must filter to predicates seen in graphData.edges
    assert "usedPredicates" in html
