"""Hand-crafted minimal graph for Phase D tests.

We do **not** depend on Phase C's writer — instead we ``CREATE`` a tiny
fixture of one Origin and seven Nodes wired with several rel-table
types. The shape:

    origin O1
    ports  pA, pB, pC                       (kind='Port')
    blob   B1                                (kind='Blob')
    module M1                                (kind='Module', name='top')
    func   F1                                (kind='Function', name='do_thing')
    extra  X1                                (kind='Module', name='other')

    M1 -[:HAS_PORT]-> pA
    M1 -[:HAS_PORT]-> pB
    M1 -[:HAS_FUNCTION]-> F1
    pA -[:DRIVES]-> B1
    B1 -[:DRIVES]-> pB
    pB -[:READS]-> pC
    M1 -[:CALLS]-> F1
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph.store import KGStore


def _create_node(
    conn,
    *,
    nid: str,
    kind: str,
    category: str,
    name: str | None,
    source: str = "sv",
    corpus: str = "fixtures",
    origin_id: str = "O1",
    s_off: int = -1,
    e_off: int = -1,
    payload: str = "{}",
) -> None:
    conn.execute(
        """
        CREATE (n:Node {
            id: $id, kind: $kind, category: $category, name: $name,
            source: $source, corpus: $corpus, origin_id: $origin_id,
            start_offset: $s_off, end_offset: $e_off,
            start_line: 0, end_line: 0, start_col: 0, end_col: 0,
            payload: $payload
        })
        """,
        {
            "id": nid, "kind": kind, "category": category, "name": name,
            "source": source, "corpus": corpus, "origin_id": origin_id,
            "s_off": s_off, "e_off": e_off, "payload": payload,
        },
    )


def _create_edge(conn, src: str, dst: str, rel: str) -> None:
    conn.execute(
        f"MATCH (a:Node), (b:Node) WHERE a.id = $a AND b.id = $b "
        f"CREATE (a)-[:{rel}]->(b)",
        {"a": src, "b": dst},
    )


@pytest.fixture()
def query_store(tmp_path: Path):
    """Build the canonical Phase-D fixture graph and yield the store."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        conn = store.conn
        # Origin row (minimal — content untouched, byte_length=0)
        conn.execute(
            """
            CREATE (o:Origin {
                id: 'O1', uri: 'file:///fake/top.sv', sha256: 'deadbeef',
                content: '', byte_length: 0, source: 'sv', corpus: 'fixtures',
                lang: 'sv', extracted_at: timestamp('2026-01-01 00:00:00')
            })
            """
        )
        # Nodes
        _create_node(conn, nid="M1", kind="Module",   category="semantic", name="top",       s_off=0, e_off=10)
        _create_node(conn, nid="F1", kind="Function", category="semantic", name="do_thing")
        _create_node(conn, nid="X1", kind="Module",   category="semantic", name="other")
        _create_node(conn, nid="pA", kind="Port",     category="semantic", name="a")
        _create_node(conn, nid="pB", kind="Port",     category="semantic", name="b")
        _create_node(conn, nid="pC", kind="Port",     category="semantic", name="c")
        _create_node(conn, nid="B1", kind="Blob",     category="blob",     name=None,
                     payload='{"k": "v"}')
        # Edges
        _create_edge(conn, "M1", "pA", "HAS_PORT")
        _create_edge(conn, "M1", "pB", "HAS_PORT")
        _create_edge(conn, "M1", "F1", "HAS_FUNCTION")
        _create_edge(conn, "pA", "B1", "DRIVES")
        _create_edge(conn, "B1", "pB", "DRIVES")
        _create_edge(conn, "pB", "pC", "READS")
        _create_edge(conn, "M1", "F1", "CALLS")
        yield store
    finally:
        store.close()
