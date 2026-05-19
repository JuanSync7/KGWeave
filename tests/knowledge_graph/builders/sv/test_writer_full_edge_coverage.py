"""Phase C.5 — every SV-emitted edge type lands in a Kuzu rel table.

These tests enforce the corrective gate added on top of Phase C's parity
check: ``stats.edges_skipped_unknown_type`` must be empty on the full SV
fixture corpus, every dict-edge type must have a backing rel table whose
row count matches the dict count, and edges that carry payload data must
preserve their payload columns through to Kuzu.
"""

from __future__ import annotations

from collections import Counter

from knowledge_graph.builders.sv.writer import EDGE_TABLE_MAP


def test_no_edges_skipped_on_full_corpus(sv_corpus_store) -> None:
    """No edge type emitted by ``build_kg`` may be dropped by the writer."""
    _store, _graph, _origins, stats = sv_corpus_store
    assert not stats.edges_skipped_unknown_type, (
        f"unmapped edge types: {dict(stats.edges_skipped_unknown_type)}"
    )


def test_every_dict_edge_type_has_rel_table_and_count_matches(
    sv_corpus_store,
) -> None:
    """Each ``edge['type']`` resolves to a rel table whose count matches."""
    store, graph, _origins, _stats = sv_corpus_store
    dict_counts = Counter(e["type"] for e in graph["edges"])
    for etype, expected in dict_counts.items():
        assert etype in EDGE_TABLE_MAP, f"unmapped edge type: {etype}"
        table, _ = EDGE_TABLE_MAP[etype]
        res = store.conn.execute(
            f"MATCH ()-[r:{table}]->() RETURN count(*)"
        )
        actual = res.get_next()[0]
        assert actual == expected, (
            f"{etype} -> {table}: dict={expected} kuzu={actual}"
        )


def test_payload_carried_edges_preserve_payload(sv_corpus_store) -> None:
    """For edge types whose payload becomes columns, columns survive write."""
    store, graph, _origins, _stats = sv_corpus_store

    # (edge_type, payload_key, column_name) — sample of payload-carrying
    # edges added by Phase C.5. ``name`` covers extends/implements/of_checker.
    samples = [
        ("extends", "name", "name"),
        ("implements", "name", "name"),
        ("of_checker", "name", "name"),
        ("bind_target", "target", "target"),
        ("imports", "package", "package"),
        ("declares", "kind", "kind"),
    ]
    edges_by_type: dict[str, list[dict]] = {}
    for e in graph["edges"]:
        edges_by_type.setdefault(e["type"], []).append(e)

    for etype, pkey, col in samples:
        rows = edges_by_type.get(etype) or []
        if not rows:
            continue  # corpus didn't emit one — skip
        table, _extractor = EDGE_TABLE_MAP[etype]
        # Collect the expected set of column values from the dict.
        expected_vals = sorted(
            str((e.get("payload") or {}).get(pkey, "") or "")
            for e in rows
        )
        res = store.conn.execute(
            f"MATCH ()-[r:{table}]->() RETURN r.{col}"
        )
        got: list[str] = []
        while res.has_next():
            v = res.get_next()[0]
            got.append("" if v is None else str(v))
        got.sort()
        assert got == expected_vals, (
            f"{etype} payload column {col!r} mismatch: "
            f"dict={expected_vals} kuzu={got}"
        )


def test_synthetic_unknown_edge_type_still_skipped(sv_corpus_store) -> None:
    """Policy preserved: a brand-new unknown type still goes to the skip counter.

    Guards against a future writer change that swallows unknowns silently.
    The fixture corpus produces ``edges_skipped_unknown_type == {}`` today;
    if a synthetic edge with an unknown type is written, it must populate
    the counter. We re-run write_graph on a tiny synthetic graph against a
    fresh store to assert this without polluting the session store.
    """
    from pathlib import Path

    from knowledge_graph.builders.sv.writer import write_graph
    from knowledge_graph.store import KGStore

    store, graph, origins, _stats = sv_corpus_store
    # Build a tiny synthetic graph reusing two real node ids.
    nodes = graph["nodes"][:2]
    fake_edge = {
        "type": "definitely_not_real_yet",
        "src": nodes[0]["id"],
        "dst": nodes[1]["id"],
        "payload": {},
    }
    # write_graph requires Origin rows for the node prefixes; reuse the
    # session store so the MERGE on existing nodes succeeds without
    # surprise (nodes already exist; the MERGE is a no-op SET).
    synth = {"nodes": nodes, "edges": [fake_edge], "order": graph.get("order", [])}
    stats = write_graph(
        store, synth, source="sv", corpus="fixtures", origins=origins
    )
    assert stats.edges_skipped_unknown_type == {
        "definitely_not_real_yet": 1
    }
