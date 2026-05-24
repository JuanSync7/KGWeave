"""Bulk-COPY writer path: semantic correctness gates for v1.5-#2.

v1.5-#2 replaced the per-row ``conn.execute(MERGE ...)`` loop in
:func:`write_graph` with a Kuzu ``COPY FROM`` bulk path when the row
count is at or above :data:`BULK_COPY_MIN_ROWS`. These tests pin the
two semantic invariants that the bulk path must preserve:

* **Replacement-merge** (G2): writing the same ``(uri, source, corpus)``
  twice with different node content keeps only the second write -- no
  doubled rows, no stale leftovers, no PK violations.
* **``_unresolved.<name>`` placeholders** (G3): edges referencing a
  not-yet-resolved cross-file symbol still materialise as synthetic
  ``category='unresolved'`` Node rows via the bulk path.

Each test forces the bulk threshold by writing N >= the threshold,
synthesized as a minimal graph so the tests stay fast (<5s each).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_graph.builders.sv import write_graph
from knowledge_graph.builders._writer_common import BULK_COPY_MIN_ROWS
from knowledge_graph.store import KGStore


def _node(nid: str, *, kind: str = "K", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": nid,
        "type": "A",
        "kind": kind,
        "is_token": False,
        "payload": payload or {},
        "span": {
            "start_offset": 0, "end_offset": 1,
            "start_line": 1, "end_line": 1,
            "start_col": 0, "end_col": 1,
        },
    }


def _graph_for(prefix: str, count: int, *, kind: str = "K") -> dict[str, Any]:
    nodes = [_node(f"{prefix}:n{i:05d}.A", kind=kind) for i in range(count)]
    edges = [
        {"src": nodes[i - 1]["id"], "dst": nodes[i]["id"],
         "type": "child", "payload": {"index": 0}}
        for i in range(1, count)
    ]
    return {"nodes": nodes, "edges": edges, "order": [n["id"] for n in nodes]}


# ---- G2: replacement-merge through bulk path -----------------------------


def test_bulk_path_replaces_same_key_with_new_content(tmp_path: Path) -> None:
    """Writing the same (uri, source, corpus) twice with different ``kind`` on
    each node keeps only the second write's content -- no duplicates, no
    stale rows from the first write. Exercises the bulk path by writing
    ``BULK_COPY_MIN_ROWS`` nodes so the COPY branch is taken (not the
    sub-threshold per-row fallback)."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    f = tmp_path / "x.sv"
    f.write_text("module x; endmodule\n")
    origin = store.snapshot_file(f, source="sv", corpus="bulk")

    n = BULK_COPY_MIN_ROWS
    g1 = _graph_for("x", n, kind="FIRST")
    write_graph(store, g1, source="sv", corpus="bulk", origins={"x": origin})

    g2 = _graph_for("x", n, kind="SECOND")
    write_graph(store, g2, source="sv", corpus="bulk", origins={"x": origin})

    total = store.conn.execute("MATCH (n:Node) RETURN count(*)").get_next()[0]
    assert total == n, f"expected {n} nodes after replacement, got {total}"

    # Every row must reflect SECOND (the replacement); no FIRST rows leak.
    first_rows = store.conn.execute(
        "MATCH (n:Node) WHERE n.kind = 'FIRST' RETURN count(*)"
    ).get_next()[0]
    assert first_rows == 0, f"stale FIRST rows leaked: {first_rows}"
    second_rows = store.conn.execute(
        "MATCH (n:Node) WHERE n.kind = 'SECOND' RETURN count(*)"
    ).get_next()[0]
    assert second_rows == n


# ---- G3: unresolved-placeholder materialisation through bulk path --------


def test_bulk_path_materialises_unresolved_placeholder(tmp_path: Path) -> None:
    """An edge whose ``dst`` is ``_unresolved.<name>`` must materialise the
    placeholder as a ``category='unresolved'`` Node row even when the
    write goes through the bulk COPY branch. Padded to >= threshold so
    the bulk path runs; the placeholder logic must not be skipped by the
    branch."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    f = tmp_path / "x.sv"
    f.write_text("module x; endmodule\n")
    origin = store.snapshot_file(f, source="sv", corpus="bulk")

    n = BULK_COPY_MIN_ROWS
    g = _graph_for("x", n)
    # Append an edge to an _unresolved.* endpoint; this placeholder is
    # NOT in graph['nodes'] and must be synthesized by write_graph.
    g["edges"].append({
        "src": g["nodes"][0]["id"],
        "dst": "_unresolved.ghost_pkg",
        "type": "imports",
        "payload": {"package": "ghost_pkg", "item": "", "unresolved": True},
    })

    stats = write_graph(
        store, g, source="sv", corpus="bulk", origins={"x": origin}
    )
    assert stats.placeholders_written == 1, stats

    row = store.conn.execute(
        "MATCH (n:Node) WHERE n.id = '_unresolved.ghost_pkg' "
        "RETURN n.category, n.name"
    ).get_next()
    assert row == ["unresolved", "ghost_pkg"], row

    # The IMPORTS edge to the placeholder must have landed too.
    edge_count = store.conn.execute(
        "MATCH (a:Node)-[r:IMPORTS]->(b:Node) "
        "WHERE b.id = '_unresolved.ghost_pkg' RETURN count(*)"
    ).get_next()[0]
    assert edge_count == 1, f"expected 1 IMPORTS edge to placeholder, got {edge_count}"
