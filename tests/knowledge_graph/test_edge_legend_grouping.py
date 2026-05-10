"""Tests for grouping edge predicates in the HTML legend by semantic class.

Predicates are partitioned into four classes (Composition, Dependency,
Dataflow, Reference). Each class is rendered as its own collapsible
section in the HTML legend, with a coherent hue palette per class so the
visual encoding is meaningful.
"""

from __future__ import annotations

import colorsys
import json
import re
import statistics
from pathlib import Path
from typing import Dict, List

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple
from kgweave.knowledge_graph.export import export_html
from kgweave.knowledge_graph.export.sigma_export import _EDGE_STYLES


_CLASS_NAMES = ("Composition", "Dependency", "Dataflow", "Reference")

# Concrete hue wedges (degrees) used for the palette assertion.
_HUE_WEDGES: Dict[str, tuple] = {
    "Composition": (0.0, 60.0),    # red-orange
    "Dependency":  (160.0, 220.0),  # cyan-blue (slight overlap with teal)
    "Dataflow":    (90.0, 160.0),   # green-teal
    "Reference":   (240.0, 320.0),  # purple (or low saturation = neutral)
}


def _hex_to_hue(hex_color: str) -> tuple:
    """Return (hue_deg, saturation) for a hex colour."""
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    return hue * 360.0, sat


def _extract_graph_data(html_path: Path) -> dict:
    text = html_path.read_text(encoding="utf-8")
    m = re.search(r"const graphData = (\{.*?\});\s*\n\s*// Build graph",
                  text, re.DOTALL)
    assert m, "Could not find embedded graphData JSON"
    return json.loads(m.group(1))


def _build_backend_with_all_predicates() -> NetworkXBackend:
    """Build a backend that contains at least one edge of every predicate."""
    backend = NetworkXBackend()
    predicates = list(_EDGE_STYLES.keys())
    entities = []
    triples = []
    for i, pred in enumerate(predicates):
        s = f"s_{pred}"
        o = f"o_{pred}"
        entities.append(Entity(name=s, type="RTL_Module"))
        entities.append(Entity(name=o, type="Signal"))
        triples.append(Triple(subject=s, predicate=pred, object=o,
                              source=f"f{i}.sv"))
    backend.upsert_entities(entities)
    backend.upsert_triples(triples)
    return backend


def test_every_predicate_has_a_class(tmp_path: Path) -> None:
    backend = _build_backend_with_all_predicates()
    out = tmp_path / "graph.html"
    export_html(backend, str(out))
    data = _extract_graph_data(out)

    edge_classes = data["legend"]["edge_classes"]
    assert isinstance(edge_classes, dict)
    assert set(edge_classes.keys()) <= set(_CLASS_NAMES)

    seen: List[str] = []
    for cls, entries in edge_classes.items():
        for entry in entries:
            assert "predicate" in entry and "color" in entry
            seen.append(entry["predicate"])

    assert set(seen) == set(_EDGE_STYLES.keys()), (
        f"Missing predicates: {set(_EDGE_STYLES) - set(seen)}; "
        f"extra: {set(seen) - set(_EDGE_STYLES)}"
    )


def test_classes_render_in_html(tmp_path: Path) -> None:
    backend = _build_backend_with_all_predicates()
    out = tmp_path / "graph.html"
    export_html(backend, str(out))
    html = out.read_text(encoding="utf-8")

    for cls in _CLASS_NAMES:
        assert cls in html, f"Class header {cls!r} missing from HTML"


def test_colors_are_within_class_palette(tmp_path: Path) -> None:
    backend = _build_backend_with_all_predicates()
    out = tmp_path / "graph.html"
    export_html(backend, str(out))
    data = _extract_graph_data(out)
    edge_classes = data["legend"]["edge_classes"]

    for cls, entries in edge_classes.items():
        wedge_lo, wedge_hi = _HUE_WEDGES[cls]
        hues = []
        for entry in entries:
            hue, sat = _hex_to_hue(entry["color"])
            # Reference class allows neutral grays (low saturation) too.
            if cls == "Reference" and sat < 0.15:
                continue
            assert wedge_lo <= hue <= wedge_hi, (
                f"{cls} predicate {entry['predicate']!r} colour "
                f"{entry['color']} hue {hue:.1f} outside wedge "
                f"[{wedge_lo}, {wedge_hi}]"
            )
            hues.append(hue)
        if len(hues) >= 2:
            # Sanity: all hues fit in a 60 degree wedge.
            assert max(hues) - min(hues) <= 60.0


def test_legend_filters_to_used_predicates(tmp_path: Path) -> None:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="A", type="RTL_Module"),
        Entity(name="B", type="Signal"),
    ])
    backend.upsert_triples([
        Triple(subject="A", predicate="drives", object="B", source="x.sv"),
    ])
    out = tmp_path / "graph.html"
    export_html(backend, str(out))
    data = _extract_graph_data(out)

    edge_classes = data["legend"]["edge_classes"]
    # Only Dataflow should be present — drives is the only edge.
    assert "Dataflow" in edge_classes
    used_preds = {e["predicate"] for e in edge_classes["Dataflow"]}
    assert used_preds == {"drives"}

    # Other classes either absent or empty.
    for cls in ("Composition", "Dependency", "Reference"):
        assert cls not in edge_classes or edge_classes[cls] == [], (
            f"{cls} should be filtered out when no edges of its class exist"
        )
