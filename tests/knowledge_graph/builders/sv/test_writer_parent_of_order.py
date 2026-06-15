"""PARENT_OF.ordinal preserves source order on retrieval."""

from __future__ import annotations


def test_parent_of_ordinal_round_trip(sv_corpus_store) -> None:
    """Pick a parent with >2 children; Cypher ORDER BY ordinal matches dict."""
    store, graph, _origins, _stats = sv_corpus_store

    # Build child-edge index from dict.
    children_by_parent: dict[str, list[tuple[int, str]]] = {}
    for e in graph["edges"]:
        if e["type"] != "child":
            continue
        children_by_parent.setdefault(e["src"], []).append(
            (int(e["payload"]["index"]), e["dst"])
        )
    # Pick the first parent with >=3 children.
    parent_id, expected = next(
        (p, sorted(kids)) for p, kids in children_by_parent.items()
        if len(kids) >= 3
    )

    res = store.conn.execute(
        """
        MATCH (p:Node {id: $pid})-[r:PARENT_OF]->(c:Node)
        RETURN c.id, r.ordinal ORDER BY r.ordinal
        """,
        {"pid": parent_id},
    )
    got: list[tuple[int, str]] = []
    while res.has_next():
        row = res.get_next()
        got.append((int(row[1]), row[0]))

    assert got == expected, (
        f"ordinal round-trip mismatch for parent {parent_id!r}\n"
        f"  expected: {expected}\n"
        f"  got     : {got}"
    )
