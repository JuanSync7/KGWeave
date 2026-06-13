"""Guard test: graph_query DSL is retired; queryable_nodes survives at its new home.

TDD anchor — written BEFORE the implementation cutover.
Expected failure state: graph_query still importable  (test_graph_query_* fail).
Expected pass state (after cutover): all assertions green.
"""

from __future__ import annotations

import importlib
import pytest


# ---------------------------------------------------------------------------
# 1. graph_query module must be gone
# ---------------------------------------------------------------------------

def test_graph_query_module_not_importable():
    """Importing the graph_query module must raise ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(
            "knowledge_graph.builders.sv.semantic.queries.graph_query"
        )


# ---------------------------------------------------------------------------
# 2. graph_query name must not be re-exported from either facade
# ---------------------------------------------------------------------------

def test_graph_query_not_in_queries_facade():
    """``graph_query`` must not appear in the queries sub-package facade."""
    import knowledge_graph.builders.sv.semantic.queries as q_pkg
    assert not hasattr(q_pkg, "graph_query"), (
        "graph_query is still re-exported from the queries facade"
    )


def test_graph_query_not_in_semantic_facade():
    """``graph_query`` must not appear in the semantic package facade."""
    import knowledge_graph.builders.sv.semantic as sem
    assert not hasattr(sem, "graph_query"), (
        "graph_query is still re-exported from the semantic facade"
    )


# ---------------------------------------------------------------------------
# 3. queryable_nodes survives — importable from connectivity and both facades
# ---------------------------------------------------------------------------

def test_queryable_nodes_importable_from_connectivity():
    """queryable_nodes must be importable directly from connectivity."""
    from knowledge_graph.builders.sv.semantic.queries.connectivity import (  # noqa: F401
        queryable_nodes,
    )
    assert callable(queryable_nodes)


def test_queryable_nodes_importable_from_queries_facade():
    """queryable_nodes must still be importable from the queries sub-package."""
    from knowledge_graph.builders.sv.semantic.queries import queryable_nodes  # noqa: F401
    assert callable(queryable_nodes)


def test_queryable_nodes_importable_from_semantic_facade():
    """queryable_nodes must still be importable from the semantic facade."""
    from knowledge_graph.builders.sv.semantic import queryable_nodes  # noqa: F401
    assert callable(queryable_nodes)


# ---------------------------------------------------------------------------
# 4. queryable_nodes behavioural smoke test (no pyslang needed)
# ---------------------------------------------------------------------------

def test_queryable_nodes_yields_queryable_only():
    """queryable_nodes yields only nodes where node['queryable'] is truthy."""
    from knowledge_graph.builders.sv.semantic.queries.connectivity import queryable_nodes

    graph = {
        "nodes": [
            {"id": "a", "queryable": True,  "type": "port"},
            {"id": "b", "queryable": False, "type": "wire"},
            {"id": "c",                     "type": "module"},   # no 'queryable' key
            {"id": "d", "queryable": True,  "type": "reg"},
        ],
        "edges": [],
    }
    ids = [n["id"] for n in queryable_nodes(graph)]
    assert ids == ["a", "d"]
