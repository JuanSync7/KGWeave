"""Every node has exactly one IN_ORIGIN edge to a real :Origin."""

from __future__ import annotations


def test_every_node_has_one_in_origin(sv_corpus_store) -> None:
    store, graph, _origins, _stats = sv_corpus_store
    res = store.conn.execute(
        """
        MATCH (n:Node)-[r:IN_ORIGIN]->(o:Origin)
        WITH n.id AS nid, count(o) AS k
        RETURN nid, k
        """
    )
    counts: dict[str, int] = {}
    while res.has_next():
        row = res.get_next()
        counts[row[0]] = int(row[1])

    # Same set of ids as the dict, and every count is exactly 1.
    dict_ids = {n["id"] for n in graph["nodes"]}
    assert set(counts.keys()) == dict_ids
    bad = {nid: k for nid, k in counts.items() if k != 1}
    assert not bad, f"nodes with non-unit IN_ORIGIN edge counts: {bad}"


def test_no_dangling_in_origin(sv_corpus_store) -> None:
    """No :Node has an IN_ORIGIN pointing to a phantom Origin id."""
    store, _graph, _origins, _stats = sv_corpus_store
    res = store.conn.execute(
        """
        MATCH (n:Node)-[:IN_ORIGIN]->(o:Origin)
        WHERE o.id IS NULL
        RETURN count(*)
        """
    )
    assert res.get_next()[0] == 0
