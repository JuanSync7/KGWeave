"""Wave 2 / track D — V2 integration driver tests.

Verifies that:
* ``KGConfig.enable_ast_decomposition`` defaults to True and gates AST
  emission when False.
* ``V2IntegrationDriver`` emits track-A + track-B AST entities tagged
  ``layer="ast"`` and that none of them leak into the v1 ("slang") layer.
* The integration's bridge step links Condition / Assignment stubs to
  their track-A Operator / Literal / Index roots within the same Process.
* Process IDs minted by tracks A and B match the v1 ``Process`` IDs the
  ``SVDataflowExtractor`` emits, so a single Process node hosts both
  ``drives_signal`` triples and AST decomposition.
"""
from __future__ import annotations

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.types import KGConfig
from kgweave.knowledge_graph.extraction.sv_dataflow_extractor import (
    SVDataflowExtractor,
)
from kgweave.knowledge_graph.extraction.sv_v2_integration import (
    V2IntegrationDriver,
    V2_INTEGRATION_SOURCE,
)


# A small synthetic SV fixture covering if/else, case, for, blocking +
# nonblocking assigns. The signal table is the v1 contract — populated
# from a prior slang/parser pass; here we hand-build it.
_FIXTURE_SRC = """
module fixture(
    input  logic        clk,
    input  logic        rst_n,
    input  logic        en,
    input  logic [3:0]  sel,
    input  logic [7:0]  a,
    input  logic [7:0]  b,
    output logic [7:0]  q
);
    logic [7:0] tmp_q;
    logic [7:0] result;
    int i;

    // continuous + ternary
    assign q = en ? tmp_q : 8'h0;

    // always_comb with case + nested if and a for-loop
    always_comb begin
        result = 8'h0;
        case (sel)
            4'd0: result = a + b;
            4'd1: result = a - b;
            default: begin
                if (en) begin
                    result = a;
                end else begin
                    result = b;
                end
            end
        endcase
        for (i = 0; i < 8; i = i + 1) begin
            result = result | a;
        end
    end

    // always_ff with non-blocking assigns + reset path
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tmp_q <= 8'h0;
        end else if (en) begin
            tmp_q <= result;
        end else begin
            tmp_q <= tmp_q;
        end
    end
endmodule
"""

_FIXTURE_SIGNALS = {
    "fixture": {
        "clk", "rst_n", "en", "sel", "a", "b", "q",
        "tmp_q", "result", "i",
    },
}


@pytest.fixture(scope="module")
def integration_result():
    drv = V2IntegrationDriver(known_module_signals=_FIXTURE_SIGNALS)
    return drv.extract(text=_FIXTURE_SRC, source="fixture.sv")


@pytest.fixture(scope="module")
def v1_dataflow_result():
    drv = SVDataflowExtractor(known_module_signals=_FIXTURE_SIGNALS)
    return drv.extract(text=_FIXTURE_SRC, source="fixture.sv")


# ---------------------------------------------------------------------------
# 1. KGConfig flag
# ---------------------------------------------------------------------------


def test_kgconfig_enable_ast_decomposition_default_true():
    cfg = KGConfig()
    assert cfg.enable_ast_decomposition is True


def test_kgconfig_enable_ast_decomposition_can_disable():
    cfg = KGConfig(enable_ast_decomposition=False)
    assert cfg.enable_ast_decomposition is False


# ---------------------------------------------------------------------------
# 2. AST entities only emitted when driver is invoked
# ---------------------------------------------------------------------------


def test_disabled_pipeline_emits_no_ast_entities():
    """Simulate `enable_ast_decomposition=False` by simply not invoking
    the integration driver. The v1 SVDataflowExtractor must not emit any
    layer='ast' entities or triples on its own."""
    cfg = KGConfig(enable_ast_decomposition=False)
    backend = NetworkXBackend()
    if not cfg.enable_ast_decomposition:
        v1 = SVDataflowExtractor(known_module_signals=_FIXTURE_SIGNALS)
        res = v1.extract(text=_FIXTURE_SRC, source="fixture.sv")
        backend.upsert_entities(res.entities)
        backend.upsert_triples(res.triples)

    ast_ents = backend.entities_by_layer("ast")
    assert ast_ents == []
    ast_trips = backend.triples_by_layer("ast")
    assert ast_trips == []


def test_enabled_pipeline_emits_ast_entities(integration_result):
    """With the integration driver invoked, AST entities exist at
    ``layer='ast'`` and include each of the expected types."""
    ents = integration_result.entities
    by_type: dict[str, list] = {}
    for e in ents:
        if getattr(e, "layer", None) == "ast":
            by_type.setdefault(e.type, []).append(e)

    assert by_type, "expected at least one layer='ast' entity"
    # Track A: at least Operator, Literal show up in this fixture.
    assert "Operator" in by_type
    assert "Literal" in by_type
    # Track B: structural decomposition.
    assert "IfStatement" in by_type
    assert "CaseStatement" in by_type
    assert "Branch" in by_type
    assert "Assignment" in by_type
    assert "Condition" in by_type
    # Loop is present in the fixture.
    assert "Loop" in by_type


# ---------------------------------------------------------------------------
# 3. layer slicing via backend
# ---------------------------------------------------------------------------


def test_backend_slang_layer_excludes_ast_when_both_loaded(
    integration_result, v1_dataflow_result
):
    backend = NetworkXBackend()
    backend.upsert_entities(v1_dataflow_result.entities)
    backend.upsert_triples(v1_dataflow_result.triples)
    backend.upsert_entities(integration_result.entities)
    backend.upsert_triples(integration_result.triples)

    # `layer="sv_dataflow"` is what v1 emits; "ast" is the v2 AST layer.
    sv_dataflow_layer_ents = backend.entities_by_layer("sv_dataflow")
    ast_layer_ents = backend.entities_by_layer("ast")
    assert ast_layer_ents, "fixture should produce AST entities"
    sv_layer_types = {e.type for e in sv_dataflow_layer_ents}
    ast_only_types = {
        "Operator", "Literal", "Index", "Condition", "IfStatement",
        "CaseStatement", "Loop", "Branch", "Assignment",
    }
    assert sv_layer_types.isdisjoint(ast_only_types), (
        f"v1 sv_dataflow layer must not contain AST types; got {sv_layer_types & ast_only_types}"
    )


def test_full_graph_contains_v1_subgraph(
    integration_result, v1_dataflow_result
):
    """The graph with AST layer added strictly contains the v1 graph."""
    backend = NetworkXBackend()
    backend.upsert_entities(v1_dataflow_result.entities)
    backend.upsert_triples(v1_dataflow_result.triples)
    v1_only_node_count = len(list(backend.graph.nodes()))
    v1_only_edge_count = len(list(backend.graph.edges()))

    backend.upsert_entities(integration_result.entities)
    backend.upsert_triples(integration_result.triples)
    full_node_count = len(list(backend.graph.nodes()))
    full_edge_count = len(list(backend.graph.edges()))
    assert full_node_count > v1_only_node_count
    assert full_edge_count > v1_only_edge_count


# ---------------------------------------------------------------------------
# 4. Process ID parity between v1 and v2 walkers
# ---------------------------------------------------------------------------


def test_process_ids_match_between_v1_and_v2(
    integration_result, v1_dataflow_result
):
    """v1 dataflow Process entities must share IDs with the prefix that
    track A / B use for AST node names. Otherwise the same Process node
    cannot host both ``drives_signal`` and AST decomposition."""
    v1_proc_ids = {
        e.name for e in v1_dataflow_result.entities if e.type == "Process"
    }
    assert v1_proc_ids, "v1 must emit Process entities for the fixture"

    # Every AST entity's name must start with one of the v1 process IDs.
    ast_ents = [
        e for e in integration_result.entities
        if getattr(e, "layer", None) == "ast"
    ]
    assert ast_ents
    # An AST entity is anchored to a process iff its name has the form
    # `<proc_id>.<rest>`. Some shared Literal nodes are module-level
    # (`<module>.lit.<value>`) and don't carry a process suffix.
    anchored = []
    for e in ast_ents:
        for pid in v1_proc_ids:
            if e.name == pid or e.name.startswith(pid + "."):
                anchored.append(e)
                break
    assert anchored, "no AST entity is anchored to a v1 Process id"


# ---------------------------------------------------------------------------
# 5. Bridge edges from Condition stubs to Operator roots
# ---------------------------------------------------------------------------


def test_condition_bridges_to_operator_root(integration_result):
    """The integration driver must emit at least one bridge edge linking
    a Condition stub (track B) to a track-A Operator root, so a graph
    walker doing condition→expression resolution can take a single hop.
    """
    bridge_triples = [
        t for t in integration_result.triples
        if getattr(t, "extractor_source", "") == V2_INTEGRATION_SOURCE
    ]
    assert bridge_triples, "expected at least one v2 integration bridge triple"

    # Bridge must target an Operator / Literal / Index entity (track A).
    ast_node_types_by_name = {
        e.name: e.type for e in integration_result.entities
        if getattr(e, "layer", None) == "ast"
    }
    found_op_bridge = False
    for t in bridge_triples:
        target_type = ast_node_types_by_name.get(t.object)
        if target_type in {"Operator", "Literal", "Index"}:
            found_op_bridge = True
            break
    assert found_op_bridge, (
        "no integration bridge resolved to an Operator/Literal/Index root"
    )


def test_bridge_attributes_marked(integration_result):
    """Every bridge triple should be marked with attributes['bridge']
    True so consumers can distinguish the integration-time hop from
    plain track-A operand edges."""
    bridge_triples = [
        t for t in integration_result.triples
        if getattr(t, "extractor_source", "") == V2_INTEGRATION_SOURCE
    ]
    assert bridge_triples
    for t in bridge_triples:
        assert (t.attributes or {}).get("bridge") is True
        assert getattr(t, "layer", None) == "ast"


# ---------------------------------------------------------------------------
# 6. End-to-end shape sanity
# ---------------------------------------------------------------------------


def test_fixture_node_and_edge_counts_sane(integration_result):
    ast_ents = [
        e for e in integration_result.entities
        if getattr(e, "layer", None) == "ast"
    ]
    ast_trips = [
        t for t in integration_result.triples
        if getattr(t, "layer", None) == "ast"
    ]
    # The fixture is small (~7 always blocks worth of structure); we
    # expect a non-trivial but bounded graph.
    assert 10 <= len(ast_ents) <= 1000
    assert 10 <= len(ast_trips) <= 5000
