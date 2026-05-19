"""Span columns survive write→Cypher; source_at(span) round-trips bytes.

Picks a sample of nodes with valid spans, fetches their (origin_id, start,
end) columns from Kuzu, calls store.source_at, and compares to the bytes
the dict computed at build time.
"""

from __future__ import annotations

import random


_INVALID = 0xFFFFFFFFF


def _expected_bytes_for(graph, nid, paths_by_prefix):
    """Read the corresponding file slice for this node's span."""
    node = next(n for n in graph["nodes"] if n["id"] == nid)
    span = node["span"]
    if span is None:
        return None
    so, eo = span["start_offset"], span["end_offset"]
    if so == _INVALID or eo == _INVALID or so > eo:
        return None
    prefix = nid.split(":", 1)[0]
    path = paths_by_prefix.get(prefix)
    if path is None:
        return None
    return path.read_bytes()[so:eo]


def test_sample_spans_round_trip(sv_corpus_store, sv_corpus_paths) -> None:
    store, graph, origins, _stats = sv_corpus_store
    paths_by_prefix = {p.stem: p for p in sv_corpus_paths}

    # Candidate nodes: structural (non-token, non-semantic-blob) with a
    # span that's plausibly real and from a fixture-stem prefix.
    candidates = [
        n["id"] for n in graph["nodes"]
        if not n.get("is_token")
        and n.get("span")
        and n["span"]["start_offset"] != _INVALID
        and n["span"]["end_offset"] != _INVALID
        and n["span"]["end_offset"] > n["span"]["start_offset"]
        and n["id"].split(":", 1)[0] in paths_by_prefix
    ]
    assert candidates, "expected at least one span-bearing node"

    rng = random.Random(20260519)
    sample = rng.sample(candidates, k=min(50, len(candidates)))

    for nid in sample:
        res = store.conn.execute(
            "MATCH (n:Node {id: $id}) "
            "RETURN n.origin_id, n.start_offset, n.end_offset",
            {"id": nid},
        )
        row = res.get_next()
        oid, so, eo = row[0], int(row[1]), int(row[2])
        assert so >= 0 and eo >= so

        cypher_bytes = store.source_at(oid, so, eo)
        expected = _expected_bytes_for(graph, nid, paths_by_prefix)
        assert expected is not None
        assert cypher_bytes == expected, (
            f"span bytes mismatch for {nid!r} "
            f"@({so},{eo}): expected {expected!r} got {cypher_bytes!r}"
        )


def test_token_span_includes_trivia(sv_corpus_store, sv_corpus_paths) -> None:
    """Tokens: source_at(span) == trivia_text + rawText (I3 invariant)."""
    store, graph, _origins, _stats = sv_corpus_store
    paths_by_prefix = {p.stem: p for p in sv_corpus_paths}

    token = next(
        n for n in graph["nodes"]
        if n.get("is_token")
        and n.get("payload", {}).get("rawText")
        and n["id"].split(":", 1)[0] in paths_by_prefix
        and n["span"]["start_offset"] != _INVALID
    )
    res = store.conn.execute(
        "MATCH (n:Node {id: $id}) "
        "RETURN n.origin_id, n.start_offset, n.end_offset",
        {"id": token["id"]},
    )
    row = res.get_next()
    oid, so, eo = row[0], int(row[1]), int(row[2])
    got = store.source_at(oid, so, eo)
    raw = token["payload"]["rawText"]
    trivia = "".join(tr.get("text", "") for tr in token["payload"].get("trivia", []))
    assert got == (trivia + raw).encode("utf-8")
