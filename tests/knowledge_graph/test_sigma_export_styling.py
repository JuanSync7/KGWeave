"""Tests for sigma_export styling and Tier-2 entity rendering."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple
from kgweave.knowledge_graph.export import export_html


_NEW_EDGE_PREDICATES = [
    "clocked_by",
    "reset_by",
    "has_fsm",
    "has_state",
    "transitions_to",
    "has_assertion",
    "references_signal",
]

_NEW_ENTITY_TYPES = [
    "ClockDomain",
    "ResetDomain",
    "FSM",
    "FSM_State",
    "SVA_Assertion",
]


def _build_backend() -> NetworkXBackend:
    backend = NetworkXBackend()
    entities = [
        Entity(name="aes_module", type="RTL_Module"),
        Entity(name="clk_main", type="ClockDomain"),
        Entity(name="rst_n", type="ResetDomain"),
        Entity(name="aes_fsm", type="FSM"),
        Entity(name="IDLE", type="FSM_State"),
        Entity(name="RUN", type="FSM_State"),
        Entity(name="aes_assert_no_x", type="SVA_Assertion"),
        Entity(name="data_in", type="Signal"),
    ]
    triples = [
        Triple(subject="aes_module", predicate="clocked_by", object="clk_main"),
        Triple(subject="aes_module", predicate="reset_by", object="rst_n"),
        Triple(subject="aes_module", predicate="has_fsm", object="aes_fsm"),
        Triple(subject="aes_fsm", predicate="has_state", object="IDLE"),
        Triple(subject="aes_fsm", predicate="has_state", object="RUN"),
        Triple(subject="IDLE", predicate="transitions_to", object="RUN"),
        Triple(subject="aes_module", predicate="has_assertion",
               object="aes_assert_no_x"),
        Triple(subject="aes_assert_no_x", predicate="references_signal",
               object="data_in"),
    ]
    backend.upsert_entities(entities)
    backend.upsert_triples(triples)
    return backend


def _extract_graph_data(html_path: Path) -> dict:
    text = html_path.read_text(encoding="utf-8")
    m = re.search(r"const graphData = (\{.*?\});\s*\n\s*// Build graph",
                  text, re.DOTALL)
    assert m, "Could not find embedded __GRAPH_DATA__ JSON"
    return json.loads(m.group(1))


def test_new_edge_predicates_have_distinct_colors(tmp_path: Path) -> None:
    backend = _build_backend()
    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    edge_styles = data["legend"]["edge_styles"]

    seen_colors: set[str] = set()
    for predicate in _NEW_EDGE_PREDICATES:
        assert predicate in edge_styles, (
            f"Edge predicate {predicate!r} missing from legend.edge_styles"
        )
        color = edge_styles[predicate]
        assert color != "#cccccc", (
            f"Edge predicate {predicate!r} has the default fallback colour"
        )
        seen_colors.add(color.lower())

    # Distinct colours among the new predicates
    assert len(seen_colors) == len(_NEW_EDGE_PREDICATES), (
        f"Expected {len(_NEW_EDGE_PREDICATES)} distinct colours, got "
        f"{len(seen_colors)}: {seen_colors}"
    )


def test_clock_reset_fsm_assertion_entities_render(tmp_path: Path) -> None:
    backend = _build_backend()
    out = tmp_path / "graph.html"
    export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    rendered_types = {n["attributes"]["entityType"] for n in data["nodes"]}

    for t in _NEW_ENTITY_TYPES:
        assert t in rendered_types, (
            f"Entity type {t!r} did not render (rendered: {rendered_types})"
        )
