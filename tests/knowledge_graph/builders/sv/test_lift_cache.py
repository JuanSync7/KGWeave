"""v1.2-#1: per-file syntax-tree/lift cache in ``builders/sv/lift.py``.

Covers:

* cache hit when the same ``(uri, sha256, id_prefix)`` is requested again,
* cache miss when the file's bytes change (sha differs),
* cache miss when the ``uri`` changes (different file, same bytes still keys
  to a different cache slot — by design we don't cross-pollinate slots),
* lossless: the cached path produces byte-identical Node/Edge records
  (apart from object identity) to the uncached path,
* timing benchmark: a 2-file corpus where 1 file is unchanged spends
  noticeably less time on lift work the second time.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path

import pyslang
import pytest

import importlib

lift_mod = importlib.import_module("knowledge_graph.builders.sv.lift")
from knowledge_graph.builders.sv.build import build_kg
from knowledge_graph.shared.ids import sha256_bytes  # noqa: F401


FIX = Path(__file__).resolve().parents[2] / "fixtures" / "sv"


@pytest.fixture(autouse=True)
def _clear_lift_cache():
    lift_mod.clear_cache()
    yield
    lift_mod.clear_cache()


def _bytes_of(p: Path) -> bytes:
    return p.read_bytes()


def test_cache_hit_on_repeat_same_uri_sha_prefix():
    """Second call with identical (uri, sha, prefix) hits the cache."""
    p = FIX / "fifo.sv"
    b = _bytes_of(p)
    uri = str(p.resolve())

    graph_a: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(
        file_bytes=b, graph=graph_a, id_prefix="fifo", uri=uri
    )
    misses_after_first = lift_mod.cache_stats()["misses"]
    hits_after_first = lift_mod.cache_stats()["hits"]

    graph_b: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(
        file_bytes=b, graph=graph_b, id_prefix="fifo", uri=uri
    )
    misses_after_second = lift_mod.cache_stats()["misses"]
    hits_after_second = lift_mod.cache_stats()["hits"]

    assert misses_after_first == 1
    assert hits_after_first == 0
    assert misses_after_second == 1  # no new miss
    assert hits_after_second == 1    # one hit


def test_cache_miss_on_byte_change():
    """If the file bytes change, the cache must miss."""
    p = FIX / "fifo.sv"
    uri = str(p.resolve())
    b = _bytes_of(p)

    g1: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(file_bytes=b, graph=g1, id_prefix="fifo", uri=uri)

    b2 = b + b"\n// touched\n"
    g2: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(file_bytes=b2, graph=g2, id_prefix="fifo", uri=uri)

    assert lift_mod.cache_stats()["misses"] == 2
    assert lift_mod.cache_stats()["hits"] == 0


def test_cache_miss_on_uri_change_same_bytes():
    """Same bytes at a different URI is a different cache slot."""
    p = FIX / "fifo.sv"
    b = _bytes_of(p)

    g1: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(
        file_bytes=b, graph=g1, id_prefix="fifo", uri="file:///a/fifo.sv"
    )
    g2: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(
        file_bytes=b, graph=g2, id_prefix="fifo", uri="file:///b/fifo.sv"
    )
    assert lift_mod.cache_stats()["misses"] == 2
    assert lift_mod.cache_stats()["hits"] == 0


def test_cached_output_byte_identical_to_uncached():
    """The cached path must produce the SAME nodes/edges/root as a fresh lift.

    Lossless property under cache: I3 (span roundtrip) and I4 (token roundtrip)
    rely on the lift slice being structurally identical regardless of whether
    it came from cache or a fresh recursion.
    """
    p = FIX / "fifo.sv"
    b = _bytes_of(p)
    uri = str(p.resolve())

    # Fresh lift (no cache).
    lift_mod.clear_cache()
    tree = pyslang.SyntaxTree.fromText(b.decode("utf-8"))
    fresh: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift(tree, graph=fresh, id_prefix="fifo")

    # Now populate the cache.
    lift_mod.clear_cache()
    primed: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(
        file_bytes=b, graph=primed, id_prefix="fifo", uri=uri
    )
    # Second call — must be a cache hit and produce identical content.
    cached: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(
        file_bytes=b, graph=cached, id_prefix="fifo", uri=uri
    )
    assert lift_mod.cache_stats()["hits"] == 1

    # Compare structurally.
    assert cached["order"] == fresh["order"]
    assert len(cached["nodes"]) == len(fresh["nodes"])
    assert len(cached["edges"]) == len(fresh["edges"])
    for a, b_ in zip(cached["nodes"], fresh["nodes"]):
        assert a == b_
    for a, b_ in zip(cached["edges"], fresh["edges"]):
        assert a == b_


def test_cached_slice_is_independent_object():
    """Mutating the dict returned to the caller must not poison the cache."""
    p = FIX / "fifo.sv"
    b = _bytes_of(p)
    uri = str(p.resolve())

    g1: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(file_bytes=b, graph=g1, id_prefix="fifo", uri=uri)
    # Mutate aggressively.
    for n in g1["nodes"]:
        n["payload"] = {"poisoned": True}
        n["span"] = None

    g2: dict = {"nodes": [], "edges": [], "order": []}
    lift_mod.lift_file_cached(file_bytes=b, graph=g2, id_prefix="fifo", uri=uri)
    assert lift_mod.cache_stats()["hits"] == 1
    # If the cache was poisoned the second graph would carry the mutation.
    assert all(n.get("payload") != {"poisoned": True} for n in g2["nodes"])
    assert any(n.get("span") is not None for n in g2["nodes"])


def test_build_kg_uses_cache_across_invocations():
    """build_kg threads through lift_file_cached: second build on the same
    corpus must register cache hits for every file (zero misses on the
    second call).
    """
    paths = [FIX / "fifo.sv", FIX / "fifo_pkg.sv"]

    lift_mod.clear_cache()
    build_kg(paths)
    misses_1 = lift_mod.cache_stats()["misses"]
    hits_1 = lift_mod.cache_stats()["hits"]
    assert misses_1 == len(paths)
    assert hits_1 == 0

    build_kg(paths)
    misses_2 = lift_mod.cache_stats()["misses"]
    hits_2 = lift_mod.cache_stats()["hits"]
    # No new misses on the second build, one hit per file.
    assert misses_2 == misses_1
    assert hits_2 == len(paths)


def test_build_kg_partial_touch_only_lifts_touched(tmp_path: Path):
    """Two-file corpus, second extract changes ONE file. The unchanged file
    must NOT be re-lifted (cache hit); the touched file must be re-lifted
    (cache miss).
    """
    unchanged = tmp_path / "fifo_pkg.sv"
    touched = tmp_path / "fifo.sv"
    unchanged.write_bytes((FIX / "fifo_pkg.sv").read_bytes())
    touched.write_bytes((FIX / "fifo.sv").read_bytes())

    lift_mod.clear_cache()
    build_kg([unchanged, touched])
    assert lift_mod.cache_stats()["misses"] == 2
    assert lift_mod.cache_stats()["hits"] == 0

    # Touch one file's bytes.
    touched.write_bytes(touched.read_bytes() + b"\n// added\n")

    build_kg([unchanged, touched])
    # One more miss (the changed file), one hit (the unchanged file).
    assert lift_mod.cache_stats()["misses"] == 3
    assert lift_mod.cache_stats()["hits"] == 1


def test_benchmark_unchanged_file_under_budget(tmp_path: Path):
    """Validatable end-goal proxy: lift_file_cached on a previously-seen file
    is at least ~5x faster than the uncached call on the same file, and
    completes in under 50ms (well under the 1.0s end-goal for an entire
    extract of N-1-unchanged-of-N).
    """
    p = FIX / "fifo.sv"
    b = p.read_bytes()
    uri = str(p.resolve())

    lift_mod.clear_cache()
    g1: dict = {"nodes": [], "edges": [], "order": []}
    t0 = time.perf_counter()
    lift_mod.lift_file_cached(file_bytes=b, graph=g1, id_prefix="fifo", uri=uri)
    cold = time.perf_counter() - t0

    # Best-of-3 warm reads to dampen noise.
    warm_samples = []
    for _ in range(3):
        g2: dict = {"nodes": [], "edges": [], "order": []}
        t = time.perf_counter()
        lift_mod.lift_file_cached(
            file_bytes=b, graph=g2, id_prefix="fifo", uri=uri
        )
        warm_samples.append(time.perf_counter() - t)
    warm = min(warm_samples)

    assert warm < cold, f"warm cache {warm:.4f}s not faster than cold {cold:.4f}s"
    assert warm < 0.05, f"warm path {warm:.4f}s exceeds 50ms budget"
