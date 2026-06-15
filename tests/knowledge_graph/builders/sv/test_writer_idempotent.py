"""MERGE-based writes are idempotent: writing the same graph twice does not
double rows.

Uses a *small* corpus subset to keep the test fast — the full-corpus parity
test already covers correctness at scale.
"""

from __future__ import annotations

from pathlib import Path

from knowledge_graph.builders.sv import build_and_store, build_kg, write_graph
from knowledge_graph.store import KGStore


def _node_count(store) -> int:
    return store.conn.execute("MATCH (n:Node) RETURN count(*)").get_next()[0]


def _parent_of_count(store) -> int:
    return store.conn.execute(
        "MATCH ()-[r:PARENT_OF]->() RETURN count(*)"
    ).get_next()[0]


def _in_origin_count(store) -> int:
    return store.conn.execute(
        "MATCH ()-[r:IN_ORIGIN]->() RETURN count(*)"
    ).get_next()[0]


def test_double_write_does_not_double_rows(tmp_path, sv_corpus_paths) -> None:
    """Re-running build_and_store on the same corpus yields identical counts."""
    # Use a small, single-file subset to bound runtime — idempotency is
    # an arithmetic property, not a corpus-size one.
    small = [p for p in sv_corpus_paths if p.name == "fifo_pkg.sv"]
    assert small, "fifo_pkg.sv fixture is required"

    store = KGStore.open(tmp_path / "kg.kuzu")
    _g1, _o1, stats1 = build_and_store(store, small, corpus="idem")
    n1, p1, io1 = _node_count(store), _parent_of_count(store), _in_origin_count(store)

    _g2, _o2, stats2 = build_and_store(store, small, corpus="idem")
    n2, p2, io2 = _node_count(store), _parent_of_count(store), _in_origin_count(store)

    assert n1 == n2, f"Node count doubled: {n1} -> {n2}"
    assert p1 == p2, f"PARENT_OF count doubled: {p1} -> {p2}"
    assert io1 == io2, f"IN_ORIGIN count doubled: {io1} -> {io2}"
    # Stats may differ (writer reports per-run counts), but DB state must match.


def test_empty_graph_is_safe(tmp_path) -> None:
    """Writing a graph with zero nodes and zero edges is a no-op."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    # No nodes -> no origin needed.
    stats = write_graph(
        store,
        {"nodes": [], "edges": [], "order": []},
        source="sv",
        corpus="empty",
        origins={},
    )
    assert stats.nodes_written == 0
    assert stats.edges_written == {}
    assert _node_count(store) == 0


def test_graph_with_nodes_but_no_edges(tmp_path) -> None:
    """A node-only graph writes nodes + IN_ORIGIN edges, no rel rows."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    f = tmp_path / "x.sv"
    f.write_text("module x; endmodule\n")
    origin = store.snapshot_file(f, source="sv", corpus="t")
    graph = {
        "nodes": [
            {
                "id": "x:n0001.A", "type": "A", "kind": "Akind",
                "is_token": False, "payload": {},
                "span": {"start_offset": 0, "end_offset": 1,
                         "start_line": 1, "end_line": 1,
                         "start_col": 0, "end_col": 1},
            },
        ],
        "edges": [],
        "order": ["x:n0001.A"],
    }
    stats = write_graph(
        store, graph, source="sv", corpus="t", origins={"x": origin}
    )
    assert stats.nodes_written == 1
    assert _node_count(store) == 1
    assert _in_origin_count(store) == 1
    assert _parent_of_count(store) == 0


def test_edge_to_missing_node_is_skipped_not_fatal(tmp_path) -> None:
    """An edge whose endpoint isn't in the graph is counted but doesn't crash."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    f = tmp_path / "x.sv"
    f.write_text("module x; endmodule\n")
    origin = store.snapshot_file(f, source="sv", corpus="t")
    graph = {
        "nodes": [
            {"id": "x:n0001.A", "type": "A", "kind": "K",
             "is_token": False, "payload": {},
             "span": {"start_offset": 0, "end_offset": 1,
                      "start_line": 1, "end_line": 1,
                      "start_col": 0, "end_col": 1}},
        ],
        "edges": [
            {"src": "x:n0001.A", "dst": "x:nMISSING", "type": "child",
             "payload": {"index": 0}},
        ],
        "order": ["x:n0001.A"],
    }
    stats = write_graph(
        store, graph, source="sv", corpus="t", origins={"x": origin}
    )
    assert stats.edges_skipped_missing_endpoint == 1
    assert _parent_of_count(store) == 0
