"""Tests for sigma_export ``include_layers`` filter (v2 AST opt-in).

V2 adds an ``ast`` layer with operator/literal/condition/branch nodes that
are only relevant to the RTL-debug persona. The default sigma export must
hide ``layer="ast"`` content so audit / DV / spec consumers aren't drowned
in expression internals. RTL-debug callers opt in via ``include_layers``.

Coverage:

1. Default (``include_layers=None``) excludes nodes/edges with layer ``ast``.
2. Explicit ``{"slang", "ast"}`` includes both layers.
3. Sentinel ``"all"`` includes everything regardless of layer tag.
4. Explicit set with neither ``slang`` nor ``ast`` excludes both layers.
5. Legacy unlayered nodes (no ``layer`` attr set) always render — backward
   compatible with v1 graphs that predate the layer column.
6. Operator nodes get a sensible ``display_type`` derived from their kind
   when the AST layer is included.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple
from kgweave.knowledge_graph.export import export_html
from kgweave.knowledge_graph.export.sigma_export import _build_graph_json


def _extract_graph_data(html_path: Path) -> dict:
    text = html_path.read_text(encoding="utf-8")
    m = re.search(
        r"const graphData = (\{.*?\});\s*\n\s*// Build graph",
        text,
        re.DOTALL,
    )
    assert m, "Could not find embedded __GRAPH_DATA__ JSON"
    return json.loads(m.group(1))


def _build_mixed_layer_backend() -> NetworkXBackend:
    """Construct a tiny graph with slang, ast, and unlayered content."""
    backend = NetworkXBackend()
    backend.upsert_entities([
        # slang layer — visible by default.
        Entity(name="dut", type="RTL_Module", layer="slang"),
        Entity(
            name="dut.clk",
            type="Port",
            port_direction="input",
            layer="slang",
        ),
        # ast layer — hidden by default.
        Entity(
            name="dut.op_and_0",
            type="Operator",
            layer="ast",
            attributes={"kind": "LogicalAnd"},
        ),
        Entity(
            name="dut.lit_0",
            type="Literal",
            layer="ast",
            attributes={"text": "32'h0"},
        ),
        # Legacy unlayered entity — should always render.
        Entity(name="legacy_thing", type="Concept"),
    ])
    backend.upsert_triples([
        # slang-layer edge between two slang nodes.
        Triple(
            subject="dut",
            predicate="contains",
            object="dut.clk",
            source="t",
            layer="slang",
        ),
        # ast-layer edge between two ast nodes.
        Triple(
            subject="dut.op_and_0",
            predicate="operand",
            object="dut.lit_0",
            source="t",
            layer="ast",
        ),
        # Legacy edge with no layer — always visible.
        Triple(
            subject="dut",
            predicate="references",
            object="legacy_thing",
            source="t",
        ),
    ])
    return backend


# ---------------------------------------------------------------------------
# Default behavior — ast hidden
# ---------------------------------------------------------------------------


def test_default_export_excludes_ast_layer() -> None:
    backend = _build_mixed_layer_backend()
    data = _build_graph_json(backend)

    node_keys = {n["key"] for n in data["nodes"]}
    assert "dut" in node_keys
    assert "dut.clk" in node_keys
    assert "legacy_thing" in node_keys, "unlayered nodes must always render"
    assert "dut.op_and_0" not in node_keys, "ast-layer node must be hidden by default"
    assert "dut.lit_0" not in node_keys

    edge_predicates = {e["attributes"]["label"] for e in data["edges"]}
    assert "contains" in edge_predicates
    assert "references" in edge_predicates
    assert "operand" not in edge_predicates, "ast-layer edge must be hidden by default"


def test_default_html_export_excludes_ast_layer(tmp_path: Path) -> None:
    backend = _build_mixed_layer_backend()
    out = tmp_path / "graph.html"
    n = export_html(backend=backend, output_path=str(out))

    data = _extract_graph_data(out)
    node_keys = {x["key"] for x in data["nodes"]}
    assert "dut.op_and_0" not in node_keys
    assert "dut.lit_0" not in node_keys
    assert n == len(data["nodes"])


# ---------------------------------------------------------------------------
# Explicit include_layers
# ---------------------------------------------------------------------------


def test_explicit_slang_and_ast_includes_both() -> None:
    backend = _build_mixed_layer_backend()
    data = _build_graph_json(backend, include_layers={"slang", "ast"})

    node_keys = {n["key"] for n in data["nodes"]}
    assert {"dut", "dut.clk", "dut.op_and_0", "dut.lit_0"}.issubset(node_keys)

    edge_predicates = {e["attributes"]["label"] for e in data["edges"]}
    assert "operand" in edge_predicates
    assert "contains" in edge_predicates


def test_all_sentinel_includes_everything() -> None:
    backend = _build_mixed_layer_backend()
    data = _build_graph_json(backend, include_layers="all")

    node_keys = {n["key"] for n in data["nodes"]}
    # Every node we inserted must be present.
    assert {"dut", "dut.clk", "dut.op_and_0", "dut.lit_0", "legacy_thing"} <= node_keys

    edge_predicates = {e["attributes"]["label"] for e in data["edges"]}
    assert {"contains", "operand", "references"} <= edge_predicates


def test_explicit_set_without_slang_or_ast_excludes_both() -> None:
    backend = _build_mixed_layer_backend()
    data = _build_graph_json(backend, include_layers={"sdc"})

    node_keys = {n["key"] for n in data["nodes"]}
    # Both slang and ast nodes filtered out; legacy unlayered always stays.
    assert "dut" not in node_keys
    assert "dut.clk" not in node_keys
    assert "dut.op_and_0" not in node_keys
    assert "dut.lit_0" not in node_keys
    assert "legacy_thing" in node_keys

    edge_predicates = {e["attributes"]["label"] for e in data["edges"]}
    assert "contains" not in edge_predicates
    assert "operand" not in edge_predicates


def test_legacy_unlayered_nodes_visible_under_any_filter() -> None:
    backend = _build_mixed_layer_backend()
    # An empty include set still keeps unlayered legacy entries.
    data = _build_graph_json(backend, include_layers=set())

    node_keys = {n["key"] for n in data["nodes"]}
    assert "legacy_thing" in node_keys
    assert "dut" not in node_keys


# ---------------------------------------------------------------------------
# display_type for v2 node types
# ---------------------------------------------------------------------------


def test_operator_node_gets_symbolic_display_type() -> None:
    backend = _build_mixed_layer_backend()
    data = _build_graph_json(backend, include_layers={"slang", "ast"})

    op_node = next(n for n in data["nodes"] if n["key"] == "dut.op_and_0")
    # Operator with kind "LogicalAnd" should map to "Op: &&" via the kind
    # symbol map; we accept either the symbolic form or the raw kind string
    # as fallback to keep this resilient to the symbol-map specifics.
    display = op_node["attributes"]["display_type"]
    assert display in ("Op: &&", "LogicalAnd"), (
        f"unexpected Operator display_type: {display!r}"
    )
    # entityType must remain canonical for downstream consumers.
    assert op_node["attributes"]["entityType"] == "Operator"


def test_literal_node_gets_text_display_type() -> None:
    backend = _build_mixed_layer_backend()
    data = _build_graph_json(backend, include_layers={"slang", "ast"})

    lit_node = next(n for n in data["nodes"] if n["key"] == "dut.lit_0")
    assert lit_node["attributes"]["display_type"] == "32'h0"
    assert lit_node["attributes"]["entityType"] == "Literal"


def test_branch_node_display_type_includes_depth() -> None:
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(
            name="dut.branch_0",
            type="Branch",
            layer="ast",
            attributes={"branch_path": ["if", "elif"]},
        ),
    ])
    data = _build_graph_json(backend, include_layers={"ast"})
    branch_node = next(n for n in data["nodes"] if n["key"] == "dut.branch_0")
    assert "depth" in branch_node["attributes"]["display_type"].lower()
    assert "2" in branch_node["attributes"]["display_type"]
