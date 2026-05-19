"""Markdown lift round-trip — every Node's span recovers the exact source slice."""

from __future__ import annotations

from pathlib import Path

from knowledge_graph import extract, open_store, source_at


def test_md_lift_roundtrips_every_node(tmp_path: Path, md_fixture_dir: Path) -> None:
    store = open_store(tmp_path / "md_lift.kuzu")
    md_paths = sorted(md_fixture_dir.glob("*.md"))

    stats = extract(store, source="md", corpus="md_lift", paths=md_paths)
    assert stats.write_stats is not None
    assert stats.write_stats.nodes_written > 0

    # Pull every MD node back with its span and verify the byte slice round-trips.
    res = store.conn.execute(
        """
        MATCH (n:Node)
        WHERE n.source = 'md' AND n.category <> 'unresolved'
        RETURN n.id, n.kind, n.origin_id, n.start_offset, n.end_offset
        """
    )
    rows = []
    while res.has_next():
        rows.append(res.get_next())
    assert rows, "expected MD nodes to be written"

    by_uri: dict[str, bytes] = {}
    for p in md_paths:
        by_uri[str(p.resolve())] = p.read_bytes()

    # Map origin_id -> raw bytes via Origin lookup.
    origin_bytes: dict[str, bytes] = {}
    for ores in (
        store.conn.execute(
            "MATCH (o:Origin) WHERE o.source = 'md' RETURN o.id, o.uri"
        ),
    ):
        while ores.has_next():
            oid, uri = ores.get_next()
            origin_bytes[oid] = by_uri[uri]

    for nid, kind, oid, start, end in rows:
        if start < 0 or end < 0:
            continue
        sliced = source_at(store, oid, start, end)
        expected = origin_bytes[oid][start:end]
        assert sliced == expected, f"round-trip mismatch for node {nid} ({kind})"

    store.close()
