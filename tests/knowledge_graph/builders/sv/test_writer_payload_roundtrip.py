"""JSON payload round-trip: semantic blobs survive write→read intact."""

from __future__ import annotations

import json


def _fetch_payload(conn, node_id: str) -> dict:
    res = conn.execute(
        "MATCH (n:Node {id: $id}) RETURN n.payload, n.name, n.kind, n.category",
        {"id": node_id},
    )
    assert res.has_next(), f"node {node_id!r} not found"
    row = res.get_next()
    return {
        "payload": json.loads(row[0]),
        "name": row[1],
        "kind": row[2],
        "category": row[3],
    }


def test_semantic_blob_payload_roundtrip(sv_corpus_store) -> None:
    """A promoted blob node's ``semantic`` data survives the JSON column."""
    store, graph, _origins, _stats = sv_corpus_store

    # Pick the first 'queryable' node that has a semantic dict.
    sample = next(
        n for n in graph["nodes"]
        if n.get("queryable") and isinstance(n.get("semantic"), dict)
    )

    got = _fetch_payload(store.conn, sample["id"])
    assert got["category"] == "semantic"
    assert got["kind"] == sample["kind"]
    assert got["payload"]["semantic"] == sample["semantic"]
    assert got["payload"]["type"] == sample["type"]
    # name column mirrors semantic.name
    assert got["name"] == sample["semantic"].get("name")


def test_token_payload_roundtrip(sv_corpus_store) -> None:
    """A Token's rawText / valueText / trivia survive the JSON column."""
    store, graph, _origins, _stats = sv_corpus_store
    sample = next(
        n for n in graph["nodes"]
        if n.get("is_token") and n.get("payload", {}).get("rawText", "")
    )
    got = _fetch_payload(store.conn, sample["id"])
    assert got["category"] == "token"
    assert got["payload"]["payload"]["rawText"] == sample["payload"]["rawText"]
    assert got["payload"]["payload"]["valueText"] == sample["payload"]["valueText"]
    # Trivia list (each {kind, text}) lossless.
    assert (
        got["payload"]["payload"].get("trivia", [])
        == sample["payload"].get("trivia", [])
    )


def test_unicode_payload_roundtrip(tmp_path) -> None:
    """A synthetic node with a Unicode-laden payload survives JSON encode/decode."""
    from knowledge_graph.builders.sv.writer import write_graph
    from knowledge_graph.schemas import OriginRef
    from knowledge_graph.store import KGStore

    store = KGStore.open(tmp_path / "kg.kuzu")
    # Snapshot a tiny file to get a real OriginRef.
    f = tmp_path / "u.sv"
    f.write_text("module u; endmodule\n")
    origin = store.snapshot_file(f, source="sv", corpus="t")
    graph = {
        "nodes": [
            {
                "id": "u:n0001.Synthetic",
                "type": "Synthetic",
                "kind": "Synthetic",
                "is_token": False,
                "queryable": True,
                "semantic": {
                    "role": "demo",
                    "name": "uni",
                    "blurb": "résumé — café — π — 漢字 — \"quoted\" — \\backslash",
                    "nested": {"list": ["α", "β", "γ", {"k": "δ"}]},
                },
                "payload": {"raw": "naïve"},
                "span": {
                    "start_offset": 0, "end_offset": 1,
                    "start_line": 1, "end_line": 1,
                    "start_col": 0, "end_col": 1,
                },
            },
        ],
        "edges": [],
        "order": ["u:n0001.Synthetic"],
    }
    write_graph(store, graph, source="sv", corpus="t",
                origins={"u": origin})

    got = _fetch_payload(store.conn, "u:n0001.Synthetic")
    assert got["payload"]["semantic"]["blurb"].startswith("résumé")
    assert got["payload"]["semantic"]["nested"]["list"][3]["k"] == "δ"
    assert got["payload"]["payload"]["raw"] == "naïve"
