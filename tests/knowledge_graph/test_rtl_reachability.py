"""Tests for RTL_Module reachability tagging and muted sigma rendering.

Covers ``NetworkXBackend.compute_rtl_reachability`` and the downstream
``sigma_export`` muted-style emission for RTL_Modules tagged
``reachable=false``. Reachability surfaces the filelist-vs-elaboration
gap that the AES demo's parser+slang pipeline otherwise leaves as
silent orphan-clusters.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple
from kgweave.knowledge_graph.export import export_html


def _backend_with(entities: list[Entity], triples: list[Triple]) -> NetworkXBackend:
    """Build a populated backend for one test (no community detection)."""
    b = NetworkXBackend()
    b.upsert_entities(entities)
    b.upsert_triples(triples)
    return b


def test_compute_rtl_reachability_simple_chain() -> None:
    ents = [
        Entity(name="A", type="RTL_Module"),
        Entity(name="B", type="RTL_Module"),
        Entity(name="C", type="RTL_Module"),
    ]
    trips = [
        Triple(subject="A", predicate="instantiates", object="B"),
        Triple(subject="B", predicate="instantiates", object="C"),
    ]
    b = _backend_with(ents, trips)
    assert b.compute_rtl_reachability("A") == {"A", "B", "C"}


def test_compute_rtl_reachability_includes_bound_into() -> None:
    ents = [
        Entity(name="A", type="RTL_Module"),
        Entity(name="B", type="RTL_Module"),
    ]
    trips = [
        Triple(subject="A", predicate="bound_into", object="B"),
    ]
    b = _backend_with(ents, trips)
    assert b.compute_rtl_reachability("B") == {"A", "B"}


def test_compute_rtl_reachability_excludes_orphan() -> None:
    ents = [
        Entity(name="A", type="RTL_Module"),
        Entity(name="B", type="RTL_Module"),
        Entity(name="C", type="RTL_Module"),
        Entity(name="D", type="RTL_Module"),
    ]
    trips = [
        Triple(subject="A", predicate="instantiates", object="B"),
        Triple(subject="B", predicate="instantiates", object="C"),
    ]
    b = _backend_with(ents, trips)
    result = b.compute_rtl_reachability("A")
    assert "D" not in result
    assert result == {"A", "B", "C"}


def test_compute_rtl_reachability_top_not_in_graph() -> None:
    b = NetworkXBackend()
    b.upsert_entities([Entity(name="X", type="RTL_Module")])
    # No raise; empty set when top is missing.
    assert b.compute_rtl_reachability("does_not_exist") == set()


def test_compute_rtl_reachability_handles_cycle() -> None:
    # Real RTL has no instantiate cycles but the BFS must terminate even
    # if the input graph is malformed (or contains parameterised back-edges).
    ents = [
        Entity(name="A", type="RTL_Module"),
        Entity(name="B", type="RTL_Module"),
    ]
    trips = [
        Triple(subject="A", predicate="instantiates", object="B"),
        Triple(subject="B", predicate="instantiates", object="A"),
    ]
    b = _backend_with(ents, trips)
    assert b.compute_rtl_reachability("A") == {"A", "B"}


def test_aes_demo_reachability_snapshot_if_present(tmp_path: Path) -> None:
    """If the AES demo has been run, assert at least one prim_* is unreachable.

    The demo writes its HTML to ``data/demo/opentitan_aes.html`` but does not
    save the backend separately, so this test is a soft assertion: it skips
    cleanly when the demo hasn't been run in this checkout.
    """
    repo = Path(__file__).resolve().parents[2]
    demo_html = repo / "data" / "demo" / "opentitan_aes.html"
    if not demo_html.exists():
        pytest.skip("AES demo HTML not present; run scripts/demo_opentitan_aes.py")
    text = demo_html.read_text(encoding="utf-8")
    # The graph data is JSON-embedded in the template via __GRAPH_DATA__.
    match = re.search(r"const graphData = (\{.*?\});", text, re.DOTALL)
    assert match is not None, "embedded graph data not found in demo HTML"
    data = json.loads(match.group(1))
    nodes = data["nodes"]
    rtl_nodes = [n for n in nodes if n["attributes"].get("entityType") == "RTL_Module"]
    if not rtl_nodes:
        pytest.skip("no RTL_Module nodes in demo export")
    # Some node should be reachable (aes itself) and some unreachable.
    reachable = [n for n in rtl_nodes if n["attributes"].get("reachable")]
    unreachable = [n for n in rtl_nodes if not n["attributes"].get("reachable")]
    assert any(n["key"] == "aes" for n in reachable), \
        "expected 'aes' RTL_Module to be reachable"
    assert len(unreachable) >= 1, \
        "expected at least one unreachable RTL_Module in AES demo"


def test_sigma_export_renders_unreachable_with_muted_style(tmp_path: Path) -> None:
    ents = [
        Entity(name="top", type="RTL_Module"),
        Entity(
            name="orphan_mod",
            type="RTL_Module",
            aliases=["reachable=false"],
        ),
    ]
    trips: list[Triple] = []
    b = _backend_with(ents, trips)
    out = tmp_path / "g.html"
    n = export_html(
        backend=b,
        output_path=str(out),
        include_types=["RTL_Module"],
    )
    assert n == 2
    # Pull the embedded JSON back out and inspect node styling.
    text = out.read_text(encoding="utf-8")
    match = re.search(r"const graphData = (\{.*?\});", text, re.DOTALL)
    assert match is not None
    data = json.loads(match.group(1))
    by_key = {n["key"]: n["attributes"] for n in data["nodes"]}
    # Unreachable node must use the muted color and reduced opacity.
    assert by_key["orphan_mod"]["color"] == "#7a8a99"
    assert by_key["orphan_mod"]["opacity"] == pytest.approx(0.6)
    assert by_key["orphan_mod"]["reachable"] is False
    # Reachable node keeps its full opacity and a different color.
    assert by_key["top"]["opacity"] == pytest.approx(1.0)
    assert by_key["top"]["reachable"] is True
    assert by_key["top"]["color"] != "#7a8a99"
