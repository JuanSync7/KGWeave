"""Micro-benchmark perf floor for :func:`write_graph` (v1.5-#2).

Baseline (per-row MERGE, pre-v1.5-#2) on this box:

* ``N=10``     ~120 ms  (12 ms/row)
* ``N=100``    ~1000 ms (10 ms/row)
* ``N=1000``   ~10.3 s  (10 ms/row)

v1.5-#2 swapped the per-row Cypher MERGE for Kuzu ``COPY FROM`` when
``N >= _BULK_COPY_MIN_ROWS`` (=100). The bulk path measured on the
same box at ``N=1000`` runs ~1s (~10x speedup vs the per-row floor).
The budgets below are set at ~1.5x the measured post-impl wall to give
jitter headroom without papering over a regression.

The sub-threshold ``N=10`` case is included to pin that we did **not**
regress the small-fixture path -- it stays on per-row INSERT (the COPY
serialise + flush overhead would otherwise lose to the per-row loop).

If the test flakes, re-run three times; only treat persistent failures
as real regressions.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from knowledge_graph.builders.sv import write_graph
from knowledge_graph.store import KGStore


def _node(nid: str) -> dict[str, Any]:
    return {
        "id": nid, "type": "A", "kind": "K", "is_token": False, "payload": {},
        "span": {"start_offset": 0, "end_offset": 1,
                 "start_line": 1, "end_line": 1,
                 "start_col": 0, "end_col": 1},
    }


def _graph(count: int) -> dict[str, Any]:
    nodes = [_node(f"x:n{i:05d}.A") for i in range(count)]
    edges = [
        {"src": nodes[i - 1]["id"], "dst": nodes[i]["id"],
         "type": "child", "payload": {"index": 0}}
        for i in range(1, count)
    ]
    return {"nodes": nodes, "edges": edges, "order": [n["id"] for n in nodes]}


def _new_store_with_origin(tmp_path: Path):
    store = KGStore.open(tmp_path / "kg.kuzu")
    f = tmp_path / "x.sv"
    f.write_text("module x; endmodule\n")
    origin = store.snapshot_file(f, source="sv", corpus="perf")
    return store, origin


# Budgets calibrated to ~1.5x post-impl measurement on this box. If
# tightened too far, will flake on noisy CI; if loosened too far, will
# silently absorb regressions.
_N1000_BUDGET_S = 3.0
_N10_BUDGET_S = 0.5


@pytest.mark.perf
@pytest.mark.timeout(30)
def test_writer_perf_n1000(tmp_path: Path) -> None:
    """Bulk-COPY path: 1000 synthetic rows must finish under the budget."""
    store, origin = _new_store_with_origin(tmp_path)
    g = _graph(1000)
    t0 = time.perf_counter()
    write_graph(store, g, source="sv", corpus="perf", origins={"x": origin})
    dt = time.perf_counter() - t0
    assert dt < _N1000_BUDGET_S, (
        f"write_graph N=1000 took {dt:.2f}s, budget {_N1000_BUDGET_S}s "
        f"-- bulk-COPY perf regressed"
    )


@pytest.mark.perf
@pytest.mark.timeout(10)
def test_writer_perf_n10_small_fixture_path(tmp_path: Path) -> None:
    """Sub-threshold (N=10): the per-row fallback path must not regress."""
    store, origin = _new_store_with_origin(tmp_path)
    g = _graph(10)
    t0 = time.perf_counter()
    write_graph(store, g, source="sv", corpus="perf", origins={"x": origin})
    dt = time.perf_counter() - t0
    assert dt < _N10_BUDGET_S, (
        f"write_graph N=10 took {dt:.2f}s, budget {_N10_BUDGET_S}s "
        f"-- small-fixture path regressed"
    )
