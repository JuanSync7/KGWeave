"""Node + edge count parity between the in-memory graph dict and Kuzu rows.

Locks the Phase C validation gate: every dict node lands as a ``:Node``
row, and every mapped edge type's Kuzu count equals the dict count.
"""

from __future__ import annotations

from collections import Counter

from knowledge_graph.builders.sv.writer import EDGE_TABLE_MAP


def test_node_count_matches_dict(sv_corpus_store) -> None:
    """Non-placeholder ``:Node`` count equals ``len(graph['nodes'])``.

    Phase C.5: ``category='unresolved'`` placeholder nodes are synthesized
    by the writer for ``_unresolved.<name>`` edge endpoints not present in
    ``graph['nodes']``. They are excluded from this dict-parity check; the
    count is tracked separately in ``stats.placeholders_written``.
    """
    store, graph, _origins, stats = sv_corpus_store
    res = store.conn.execute(
        "MATCH (n:Node) WHERE n.category <> 'unresolved' RETURN count(*)"
    )
    kuzu_count = res.get_next()[0]
    assert kuzu_count == len(graph["nodes"])
    assert stats.nodes_written == len(graph["nodes"])


def test_edge_parity_per_type(sv_corpus_store) -> None:
    """For every mapped edge type, dict count == Kuzu rel-table count."""
    store, graph, _origins, stats = sv_corpus_store
    dict_counts = Counter(e["type"] for e in graph["edges"])

    for edge_type, (table, _payload) in EDGE_TABLE_MAP.items():
        expected = dict_counts.get(edge_type, 0)
        res = store.conn.execute(f"MATCH ()-[r:{table}]->() RETURN count(*)")
        actual = res.get_next()[0]
        assert actual == expected, (
            f"{edge_type} -> {table}: dict={expected} kuzu={actual}"
        )
        assert stats.edges_written.get(table, 0) == expected


def test_unmapped_edge_types_are_counted_not_silently_dropped(
    sv_corpus_store,
) -> None:
    """Edge types absent from EDGE_TABLE_MAP must be reported in stats."""
    _store, graph, _origins, stats = sv_corpus_store
    dict_counts = Counter(e["type"] for e in graph["edges"])
    for etype, n in dict_counts.items():
        if etype in EDGE_TABLE_MAP:
            continue
        # Either the edge type appears in the skipped-unknown counter
        # with the right tally, or it's the empty case (n==0).
        assert stats.edges_skipped_unknown_type.get(etype, 0) == n
