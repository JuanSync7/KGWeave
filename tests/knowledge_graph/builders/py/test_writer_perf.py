"""Micro-benchmark perf floor for :func:`write_py_graph` (v1.6-#4).

Mirrors :mod:`tests.knowledge_graph.builders.sv.test_writer_perf`. The
charter §4 budget is **N=1000 Py-write wall ≤ 2× SV-write wall**. SV's
N=1000 budget is 3.0 s, so the Py N=1000 budget is **6.0 s**.

Pre-impl this test fails: ``write_py_graph`` was per-row Cypher at
~10 ms/row, i.e. ~10 s for N=1000. Post-impl (bulk-COPY ≥
``_BULK_COPY_MIN_ROWS``) should land well under budget — same shape as
the SV speedup (~10×).

A sub-threshold ``N=10`` case pins that we did **not** regress the
small-fixture path — it must stay on per-row INSERT (the CSV serialise
+ COPY-parse cost would otherwise lose on tiny batches).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from knowledge_graph.builders.py.walker import PyNode
from knowledge_graph.builders.py.writer import write_py_graph
from knowledge_graph.store import KGStore


def _py_nodes(count: int) -> list[PyNode]:
    """One PyModule root + ``count-1`` PyFunction children, all parented
    to the root. Mirrors the shape SV's ``_graph`` produces — a linear
    parent chain large enough to exercise the writer's hot path."""
    nodes: list[PyNode] = [
        PyNode(kind="PyModule", start=0, end=count * 16, name="", parent_idx=None)
    ]
    for i in range(1, count):
        nodes.append(
            PyNode(
                kind="PyFunction",
                start=i * 16,
                end=i * 16 + 8,
                name=f"fn_{i:05d}",
                parent_idx=0,
            )
        )
    return nodes


def _new_store_with_origin(tmp_path: Path):
    store = KGStore.open(tmp_path / "kg.kuzu")
    f = tmp_path / "x.py"
    # Bytes long enough that synthetic offsets in _py_nodes stay valid
    # for _line_col (offset > 0 indexes into the content). For N=1000
    # we need at least 16_000 bytes.
    f.write_bytes(b"x = 1\n" * 4000)
    origin = store.snapshot_file(f, source="py", corpus="perf", lang="python")
    return store, origin, f.read_bytes()


# Budget per charter §4: ≤ 2× the SV N=1000 budget (3.0 s) = 6.0 s.
_N1000_BUDGET_S = 6.0
# Sub-threshold: same generous cold-start budget the SV test uses.
_N10_BUDGET_S = 1.5


@pytest.mark.perf
@pytest.mark.timeout(30)
def test_py_writer_perf_n1000(tmp_path: Path) -> None:
    """Bulk-COPY path: 1000 PyNodes must finish under 2× the SV budget."""
    store, origin, content = _new_store_with_origin(tmp_path)
    nodes = _py_nodes(1000)
    t0 = time.perf_counter()
    write_py_graph(
        store, nodes, content=content, origin=origin, source="py", corpus="perf"
    )
    dt = time.perf_counter() - t0
    assert dt < _N1000_BUDGET_S, (
        f"write_py_graph N=1000 took {dt:.2f}s, budget {_N1000_BUDGET_S}s "
        f"-- bulk-COPY parity with SV regressed (or never wired)"
    )


@pytest.mark.perf
@pytest.mark.timeout(10)
def test_py_writer_perf_n10_small_fixture_path(tmp_path: Path) -> None:
    """Sub-threshold (N=10): per-row fallback must not regress."""
    store, origin, content = _new_store_with_origin(tmp_path)
    nodes = _py_nodes(10)
    t0 = time.perf_counter()
    write_py_graph(
        store, nodes, content=content, origin=origin, source="py", corpus="perf"
    )
    dt = time.perf_counter() - t0
    assert dt < _N10_BUDGET_S, (
        f"write_py_graph N=10 took {dt:.2f}s, budget {_N10_BUDGET_S}s "
        f"-- small-fixture path regressed"
    )
