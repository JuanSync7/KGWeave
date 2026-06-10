"""Walking skeleton — Cypher pipe end-to-end (Slice S0).

Validates that the full pipe:
  build_kg → _kuzu_load → cypher_query → CypherResult → facade

works with a trivial query.  kuzu must be lazy-imported so the module loads
without kuzu present; structural `child` edges and `_unresolved` targets must
NOT be loaded into node table N.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Graph fixture
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_CORPUS = sorted((_ROOT / "corpus").glob("*.sv"))


@pytest.fixture(scope="module")
def graph():
    from research.ast_experiment.src.build import build_kg
    g, _, _ = build_kg(_CORPUS)
    return g


# ---------------------------------------------------------------------------
# Unit: _kuzu_load
# ---------------------------------------------------------------------------


class TestKuzuLoad:
    def test_returns_connection(self, graph):
        """_kuzu_load(graph) returns a (kuzu.Connection, tmpdir) tuple."""
        import shutil
        import kuzu
        from research.ast_experiment.src.semantic.queries._kuzu_load import _kuzu_load
        conn, tmpdir = _kuzu_load(graph)
        assert isinstance(conn, kuzu.Connection)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_n_row_count_matches_promoted_nodes(self, graph):
        """N row count == number of promoted (queryable) nodes."""
        import shutil
        from research.ast_experiment.src.semantic.queries._kuzu_load import _kuzu_load
        from research.ast_experiment.src.semantic import queryable_nodes

        conn, tmpdir = _kuzu_load(graph)
        try:
            res = conn.execute("MATCH (n:N) RETURN count(n) AS c")
            count = res.get_next()[0]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        expected = len(list(queryable_nodes(graph)))
        assert count == expected

    def test_child_edges_absent(self, graph):
        """child edges must NOT be loaded into any rel table."""
        from research.ast_experiment.src.semantic.queries._kuzu_load import _kuzu_load, _EDGE_TYPES
        assert "child" not in _EDGE_TYPES(graph), "child must not be an edge type"

    def test_unresolved_targets_absent(self, graph):
        """Edges whose target is _unresolved must be skipped."""
        import shutil
        from research.ast_experiment.src.semantic.queries._kuzu_load import _kuzu_load
        conn, tmpdir = _kuzu_load(graph)
        try:
            # If _unresolved targets are loaded, some node's id would start with _unresolved
            res = conn.execute("MATCH (n:N) WHERE n.id STARTS WITH '_unresolved' RETURN count(n)")
            count = res.get_next()[0]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        assert count == 0, "No _unresolved nodes should be in table N"


# ---------------------------------------------------------------------------
# Integration: cypher_query function
# ---------------------------------------------------------------------------


class TestCypherQuery:
    def test_returns_cypher_result(self, graph):
        """cypher_query returns a CypherResult."""
        from research.ast_experiment.src.semantic.queries.cypher_query import (
            cypher_query, CypherResult,
        )
        result = cypher_query(graph, "MATCH (n:N) RETURN n.name LIMIT 1")
        assert isinstance(result, CypherResult)

    def test_one_column(self, graph):
        """MATCH (n:N) RETURN n.name LIMIT 1 → exactly 1 column."""
        from research.ast_experiment.src.semantic.queries.cypher_query import cypher_query
        result = cypher_query(graph, "MATCH (n:N) RETURN n.name LIMIT 1")
        assert len(result.columns) == 1

    def test_one_row(self, graph):
        """MATCH (n:N) RETURN n.name LIMIT 1 → exactly 1 row."""
        from research.ast_experiment.src.semantic.queries.cypher_query import cypher_query
        result = cypher_query(graph, "MATCH (n:N) RETURN n.name LIMIT 1")
        assert len(result.rows) == 1

    def test_scalars_convenience(self, graph):
        """CypherResult.scalars() returns a flat list for single-column queries."""
        from research.ast_experiment.src.semantic.queries.cypher_query import cypher_query
        result = cypher_query(graph, "MATCH (n:N) RETURN n.name LIMIT 1")
        s = result.scalars()
        assert isinstance(s, list)
        # single-column → same length as rows (Nones dropped)
        non_null_rows = [r for r in result.rows if list(r.values())[0] is not None]
        assert len(s) == len(non_null_rows)

    def test_module_import_does_not_require_kuzu(self):
        """Importing cypher_query module must NOT require kuzu at import time."""
        import importlib
        import sys
        # Remove kuzu from sys.modules temporarily to verify lazy import
        kuzu_mod = sys.modules.pop("kuzu", None)
        try:
            # Force reimport of the module
            if "research.ast_experiment.src.semantic.queries.cypher_query" in sys.modules:
                del sys.modules["research.ast_experiment.src.semantic.queries.cypher_query"]
            # This should NOT raise even without kuzu
            mod = importlib.import_module(
                "research.ast_experiment.src.semantic.queries.cypher_query"
            )
            assert hasattr(mod, "cypher_query")
            assert hasattr(mod, "CypherResult")
        finally:
            # Restore kuzu
            if kuzu_mod is not None:
                sys.modules["kuzu"] = kuzu_mod


# ---------------------------------------------------------------------------
# Leak regression: cypher_query must not accumulate kg_kuzu_* temp dirs
# ---------------------------------------------------------------------------


class TestNoTempLeak:
    def test_cypher_query_cleans_up_tempdir(self, graph):
        """cypher_query must remove every kg_kuzu_* temp dir it creates.

        Snapshot the set of kg_kuzu_* dirs before, run several calls, then
        assert that no new kg_kuzu_* dirs remain.
        """
        import glob
        import os
        import tempfile

        from research.ast_experiment.src.semantic import cypher_query

        pattern = os.path.join(tempfile.gettempdir(), "kg_kuzu_*")
        before = set(glob.glob(pattern))

        # Run several calls so any leak would be visible
        for _ in range(3):
            cypher_query(graph, "MATCH (n:N) RETURN n.name LIMIT 1")

        after = set(glob.glob(pattern))
        new_dirs = after - before
        assert new_dirs == set(), (
            f"cypher_query leaked {len(new_dirs)} temp dir(s): {sorted(new_dirs)}"
        )


# ---------------------------------------------------------------------------
# E2E: facade import path
# ---------------------------------------------------------------------------


class TestFacade:
    def test_facade_exports_cypher_query(self):
        """cypher_query is importable from the semantic facade."""
        from research.ast_experiment.src.semantic import cypher_query  # noqa: F401
        assert callable(cypher_query)

    def test_facade_exports_cypher_result(self):
        """CypherResult is importable from the semantic facade."""
        from research.ast_experiment.src.semantic import CypherResult  # noqa: F401
        assert CypherResult is not None

    def test_facade_end_to_end(self, graph):
        """E2E: facade cypher_query returns CypherResult with 1 col, 1 row (validable_outcome)."""
        from research.ast_experiment.src.semantic import cypher_query, CypherResult
        result = cypher_query(graph, "MATCH (n:N) RETURN n.name LIMIT 1")
        assert isinstance(result, CypherResult)
        assert len(result.columns) == 1
        assert len(result.rows) == 1
