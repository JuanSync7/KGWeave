"""Slice S1 — Core read capability + result contract.

Validable outcome: the five A/B query shapes (single-hop containment,
edge-union, multi-column return, aggregation, 2-hop dataflow) executed via
``cypher_query`` each return a result set equal to the question's independent
``truth_fn`` (name- OR path-projection accepted); node-valued columns
(``RETURN s``) are hydrated to a ``SemanticNode`` (id, role, name, path,
attributes) looked up by id from ``graph["nodes"]``, while scalar projections
stay scalar.

These tests reuse the proven A/B oracle questions (Q1, Q2, Q4, Q5, Q6) and
their independent ``truth_fn`` / ``accept_fns`` from
``evals/cypher_ab/questions.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research.ast_experiment.evals.cypher_ab.questions import QUESTIONS

# ---------------------------------------------------------------------------
# Graph fixture — same setup as test_cypher_skeleton.py / run_ab.py
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_CORPUS = sorted((_ROOT / "corpus").glob("*.sv"))


@pytest.fixture(scope="module")
def graph():
    from research.ast_experiment.src.build import build_kg

    g, _, _ = build_kg(_CORPUS)
    return g


_QBYID = {q.id: q for q in QUESTIONS}


def _acceptable(q, graph) -> list[frozenset[str]]:
    """Truth + accept_fns projections (name-vs-path orthogonal lever)."""
    return q.acceptable(graph)


def _run_set(graph, cypher_oracle: str) -> frozenset[str]:
    """Execute the oracle Cypher and project the single column to a string set."""
    from research.ast_experiment.src.semantic import cypher_query

    result = cypher_query(graph, cypher_oracle)
    assert len(result.columns) == 1, (
        f"expected single-column oracle, got {result.columns}"
    )
    col = result.columns[0]
    return frozenset(
        str(row[col]) for row in result.rows if row[col] is not None
    )


# ---------------------------------------------------------------------------
# Q1 — single-hop containment (RETURN m.name)
# ---------------------------------------------------------------------------


def test_q1_methods_single_hop(graph):
    q = _QBYID["Q1_methods"]
    got = _run_set(graph, q.cypher_oracle)
    acc = _acceptable(q, graph)
    assert any(got == t for t in acc), f"Q1 got={sorted(got)} acceptable={acc}"


# ---------------------------------------------------------------------------
# Q2 — edge-union (has_port|has_net)
# ---------------------------------------------------------------------------


def test_q2_ports_or_nets_edge_union(graph):
    q = _QBYID["Q2_ports_or_nets"]
    got = _run_set(graph, q.cypher_oracle)
    acc = _acceptable(q, graph)
    assert any(got == t for t in acc), f"Q2 got={sorted(got)} acceptable={acc}"


# ---------------------------------------------------------------------------
# Q4 — multi-column return (RETURN i.path, m.name) — pipe-joined
# ---------------------------------------------------------------------------


def test_q4_inst_module_pairs_multicolumn(graph):
    from research.ast_experiment.src.semantic import cypher_query

    q = _QBYID["Q4_inst_module_pairs"]
    result = cypher_query(graph, q.cypher_oracle)
    assert len(result.columns) == 2, (
        f"Q4 expected 2 columns, got {result.columns}"
    )
    c0, c1 = result.columns
    got = frozenset(
        f"{row[c0]}|{row[c1]}"
        for row in result.rows
        if row[c0] is not None and row[c1] is not None
    )
    acc = _acceptable(q, graph)
    assert any(got == t for t in acc), f"Q4 got={sorted(got)} acceptable={acc}"


# ---------------------------------------------------------------------------
# Q5 — aggregation (RETURN count(p)) — truth is a 1-element set of the count
# as a string
# ---------------------------------------------------------------------------


def test_q5_port_count_aggregation(graph):
    from research.ast_experiment.src.semantic import cypher_query

    q = _QBYID["Q5_port_count"]
    result = cypher_query(graph, q.cypher_oracle)
    assert len(result.columns) == 1, (
        f"Q5 expected 1 column, got {result.columns}"
    )
    col = result.columns[0]
    got = frozenset(str(row[col]) for row in result.rows if row[col] is not None)
    acc = _acceptable(q, graph)
    assert any(got == t for t in acc), f"Q5 got={sorted(got)} acceptable={acc}"


# ---------------------------------------------------------------------------
# Q6 — 2-hop dataflow (RETURN DISTINCT s.name)
# ---------------------------------------------------------------------------


def test_q6_driver_reads_full_two_hop(graph):
    q = _QBYID["Q6_driver_reads_full"]
    got = _run_set(graph, q.cypher_oracle)
    acc = _acceptable(q, graph)
    assert any(got == t for t in acc), f"Q6 got={sorted(got)} acceptable={acc}"


# ---------------------------------------------------------------------------
# HYDRATION — RETURN s (a whole node) yields a SemanticNode carrying name AND
# path AND the nested attributes dict (proving hydration by id, not the
# flattened kuzu row, which loses semantic.attributes).
# ---------------------------------------------------------------------------


def test_return_node_hydrates_to_semantic_node(graph):
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import SemanticNode

    # fifo.full is a port — its semantic.attributes carries a `direction` key
    # which the flattened kuzu row also has, but more importantly proving the
    # whole nested attributes dict is restored (not the flat row).
    result = cypher_query(
        graph,
        "MATCH (s:N) WHERE s.path='fifo.full' RETURN s",
    )
    assert len(result.columns) == 1
    col = result.columns[0]
    cells = [row[col] for row in result.rows]
    assert len(cells) == 1, f"expected exactly one fifo.full node, got {cells}"
    sn = cells[0]
    assert isinstance(sn, SemanticNode), f"expected SemanticNode, got {type(sn)}"
    assert sn.name is not None and sn.name != "", "name must be hydrated"
    assert sn.path == "fifo.full", f"path must be hydrated, got {sn.path!r}"
    assert isinstance(sn.attributes, dict)
    assert sn.attributes, "attributes dict must be non-empty (hydrated by id)"
    assert "direction" in sn.attributes, (
        f"expected 'direction' attribute, got {sn.attributes}"
    )
    # id and role are part of the contract too
    assert sn.id, "id must be populated"
    assert sn.role, "role must be populated"


def test_return_node_attributes_match_graph_block(graph):
    """The hydrated attributes equal the node's own semantic.attributes block,
    confirming lookup-by-id (not the flat kuzu row)."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import SemanticNode

    result = cypher_query(
        graph,
        "MATCH (s:N) WHERE s.path='fifo.full' RETURN s",
    )
    sn = result.rows[0][result.columns[0]]
    assert isinstance(sn, SemanticNode)

    by_id = {n["id"]: n for n in graph["nodes"]}
    node = by_id[sn.id]
    sem = node["semantic"]
    assert sn.name == sem.get("name")
    assert sn.path == sem.get("path")
    assert sn.role == sem.get("role")
    assert sn.attributes == (sem.get("attributes") or {})


def test_scalar_projection_stays_scalar(graph):
    """A scalar projection (s.name) is NOT wrapped — it stays a plain str."""
    from research.ast_experiment.src.semantic import cypher_query

    result = cypher_query(
        graph,
        "MATCH (s:N) WHERE s.path='fifo.full' RETURN s.name",
    )
    val = result.rows[0][result.columns[0]]
    assert isinstance(val, str), f"scalar projection must stay scalar, got {type(val)}"


def test_semantic_node_exported_alongside_cypher_result():
    """SemanticNode is exported alongside CypherResult from cypher_query.py
    (the module that owns the result contract). Facade wiring is a later slice.
    """
    from research.ast_experiment.src.semantic.queries.cypher_query import (  # noqa: F401
        CypherResult,
        SemanticNode,
    )

    assert SemanticNode is not None
