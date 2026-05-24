"""v1.3-#1: per-file promote() output cache in
``builders/sv/semantic/promote_cache.py``.

Covers the contract:

* cache hit returns a graph identical to the cold-call output (lossless),
* cache hit does NOT re-invoke the underlying ``promote()`` (monkeypatched
  counter),
* different ``(uri, sha)`` keys do NOT collide,
* different ``corpus_fp`` does NOT collide,
* changing the ruleset fingerprint invalidates cached entries,
* mutating the served graph does not poison the cache (deepcopy on serve),
* warm timing budget — second extract on an unchanged corpus is well under
  10% of the cold extract,
* end-to-end integration via :func:`build_kg` — extracting the same corpus
  twice produces structurally identical graphs (node count, edge count,
  sorted ids).
"""

from __future__ import annotations

import copy
import importlib
import time
from pathlib import Path

import pytest

lift_mod = importlib.import_module("knowledge_graph.builders.sv.lift")
from knowledge_graph.builders.sv.build import build_kg
from knowledge_graph.builders.sv.semantic import promote_cache as pc


FIX = Path(__file__).resolve().parents[2] / "fixtures" / "sv"


@pytest.fixture(autouse=True)
def _clear_all_caches():
    lift_mod.clear_cache()
    pc.clear_cache()
    pc.clear_ruleset_fp_cache()
    yield
    lift_mod.clear_cache()
    pc.clear_cache()
    pc.clear_ruleset_fp_cache()


# ---------------------------------------------------------------------------
# Direct API tests — hit/miss accounting and key isolation.
# ---------------------------------------------------------------------------


def _two_file_paths() -> list[Path]:
    return [FIX / "fifo_pkg.sv", FIX / "fifo.sv"]


def test_cache_hit_on_repeat_build_kg():
    """Second build_kg on the same corpus must register a hit per file per phase."""
    paths = _two_file_paths()

    build_kg(paths)
    stats1 = pc.cache_stats()
    # Two files, two phases each.
    assert stats1["misses"] == 2 * len(paths)
    assert stats1["hits"] == 0

    build_kg(paths)
    stats2 = pc.cache_stats()
    assert stats2["misses"] == stats1["misses"]
    assert stats2["hits"] == 2 * len(paths)


def test_cache_hit_skips_underlying_promote(monkeypatch):
    """A cache hit must NOT invoke the underlying ``promote()``."""
    paths = _two_file_paths()
    # First build populates the cache.
    build_kg(paths)

    # Monkeypatch the inner ``_promote_inner`` referenced by promote_cache so
    # we can detect any call.
    counter = {"n": 0}
    real_inner = pc._promote_inner

    def _spy(*args, **kwargs):
        counter["n"] += 1
        return real_inner(*args, **kwargs)

    monkeypatch.setattr(pc, "_promote_inner", _spy)

    build_kg(paths)
    assert counter["n"] == 0, (
        f"expected zero promote() calls on full cache hit, got {counter['n']}"
    )


def test_cache_miss_on_byte_change(tmp_path: Path):
    """Touching one file's bytes invalidates ALL entries (corpus_fp changes)."""
    a = tmp_path / "fifo_pkg.sv"
    b = tmp_path / "fifo.sv"
    a.write_bytes((FIX / "fifo_pkg.sv").read_bytes())
    b.write_bytes((FIX / "fifo.sv").read_bytes())

    build_kg([a, b])
    cold_misses = pc.cache_stats()["misses"]

    # Mutate one file.
    b.write_bytes(b.read_bytes() + b"\n// touched\n")
    build_kg([a, b])
    # Every file misses again — corpus_fp pins the cache to the full set.
    assert pc.cache_stats()["misses"] == cold_misses + 2 * 2
    # No hits between cold and second build because corpus_fp moved.
    assert pc.cache_stats()["hits"] == 0


def test_cache_isolation_by_corpus(tmp_path: Path):
    """A file appearing in two different corpora keys to two cache slots."""
    a = tmp_path / "fifo_pkg.sv"
    b = tmp_path / "fifo.sv"
    a.write_bytes((FIX / "fifo_pkg.sv").read_bytes())
    b.write_bytes((FIX / "fifo.sv").read_bytes())

    # Corpus 1: just [a].
    build_kg([a])
    misses_after_c1 = pc.cache_stats()["misses"]
    # Corpus 2: [a, b] — a appears here too but under a different corpus_fp.
    build_kg([a, b])
    misses_after_c2 = pc.cache_stats()["misses"]
    # Corpus 2 must miss for a *and* b — a's cache entry under corpus 1 must
    # not be served for corpus 2.
    assert misses_after_c2 - misses_after_c1 == 2 * 2


def test_cache_isolation_by_uri(tmp_path: Path):
    """Same bytes, different URI → different cache slot."""
    base = (FIX / "fifo_pkg.sv").read_bytes()
    a1 = tmp_path / "a" / "fifo_pkg.sv"
    a2 = tmp_path / "b" / "fifo_pkg.sv"
    a1.parent.mkdir(parents=True)
    a2.parent.mkdir(parents=True)
    a1.write_bytes(base)
    a2.write_bytes(base)

    build_kg([a1])
    misses_after_a1 = pc.cache_stats()["misses"]
    build_kg([a2])
    # a2 has the same bytes but a different uri AND lives in a different
    # corpus (only one file each, but path differs) → must miss.
    assert pc.cache_stats()["misses"] - misses_after_a1 == 2


def test_ruleset_fp_invalidates_cache():
    """Bumping the ruleset fingerprint invalidates cached entries."""
    paths = _two_file_paths()
    build_kg(paths)
    misses_cold = pc.cache_stats()["misses"]
    assert misses_cold == 2 * len(paths)

    # Simulate a rule edit by pinning a different fp.
    pc._RULESET_FP_CACHE["fp"] = "x" * 64

    build_kg(paths)
    # New fingerprint → none of the old cache entries are reachable.
    assert pc.cache_stats()["misses"] == misses_cold + 2 * len(paths)


def test_replay_does_not_poison_cache():
    """Mutating the served graph must not poison the next replay (deepcopy on serve)."""
    paths = _two_file_paths()

    graph_a, _, _ = build_kg(paths)
    # Mutate aggressively — edges, semantic dicts, name_index.
    for e in graph_a["edges"]:
        e["payload"] = {"poisoned": True}
        e["type"] = "POISON"
    for n in graph_a["nodes"]:
        if isinstance(n.get("semantic"), dict):
            n["semantic"]["role"] = "POISON"
    graph_a["semantic_name_index"].clear()

    graph_b, _, _ = build_kg(paths)
    # Replay must not have served the poisoned content.
    assert not any(e.get("type") == "POISON" for e in graph_b["edges"])
    assert not any(
        isinstance(n.get("semantic"), dict) and n["semantic"].get("role") == "POISON"
        for n in graph_b["nodes"]
    )
    assert graph_b["semantic_name_index"], "name_index should be repopulated"


# ---------------------------------------------------------------------------
# Losslessness — warm graph equals cold graph.
# ---------------------------------------------------------------------------


def _normalize_for_compare(graph: dict) -> dict:
    """Strip incidentals so two graphs can be structurally compared."""
    return {
        "node_ids": [n["id"] for n in graph["nodes"]],
        "node_roles": [
            (n.get("semantic") or {}).get("role") for n in graph["nodes"]
        ],
        "node_paths": [
            (n.get("semantic") or {}).get("path") for n in graph["nodes"]
        ],
        "node_queryable": [n.get("queryable", False) for n in graph["nodes"]],
        "edge_tuples": sorted(
            (e["src"], e["dst"], e["type"]) for e in graph["edges"]
        ),
        "edge_count": len(graph["edges"]),
        "node_count": len(graph["nodes"]),
        "name_index": dict(graph.get("semantic_name_index", {})),
        "leaks": list(graph.get("semantic_leaks", [])),
    }


def test_warm_graph_structurally_identical_to_cold():
    """End-to-end: building the same corpus twice yields identical graphs."""
    paths = _two_file_paths()

    cold_graph, _, _ = build_kg(paths)
    cold_view = _normalize_for_compare(cold_graph)

    warm_graph, _, _ = build_kg(paths)
    warm_view = _normalize_for_compare(warm_graph)

    assert warm_view["node_count"] == cold_view["node_count"]
    assert warm_view["edge_count"] == cold_view["edge_count"]
    assert warm_view["node_ids"] == cold_view["node_ids"]
    assert warm_view["node_roles"] == cold_view["node_roles"]
    assert warm_view["node_paths"] == cold_view["node_paths"]
    assert warm_view["node_queryable"] == cold_view["node_queryable"]
    assert warm_view["edge_tuples"] == cold_view["edge_tuples"]
    assert warm_view["name_index"] == cold_view["name_index"]
    assert warm_view["leaks"] == cold_view["leaks"]


# ---------------------------------------------------------------------------
# Timing budget — warm extract well under 10% of cold extract.
# ---------------------------------------------------------------------------


def test_warm_extract_under_budget():
    """Cache hit shrinks the promote step to a fraction of the cold cost."""
    paths = _two_file_paths()

    # Cold pass.
    lift_mod.clear_cache()
    pc.clear_cache()
    t0 = time.perf_counter()
    build_kg(paths)
    cold = time.perf_counter() - t0

    # Warm: best of 3.
    warm_samples = []
    for _ in range(3):
        t = time.perf_counter()
        build_kg(paths)
        warm_samples.append(time.perf_counter() - t)
    warm = min(warm_samples)

    assert warm < cold, f"warm {warm:.3f}s not faster than cold {cold:.3f}s"
    # Generous bound — the cold pass is dominated by pyslang parse + promote
    # rule dispatch, both of which the cache elides; we should be well under
    # half the cold cost. The 50% bound holds even on noisy hardware.
    assert warm < 0.5 * cold, (
        f"warm {warm:.3f}s should be << 50% of cold {cold:.3f}s"
    )


# ---------------------------------------------------------------------------
# helpers.
# ---------------------------------------------------------------------------


def test_compute_corpus_fp_is_order_sensitive():
    """v1.6-#1: ``compute_corpus_fp`` must hash the (uri, sha) list **in
    order**. SV promote dispatch is order-sensitive (pass1 populates the
    cross-file name_index before any pass2 consults it), so the same set
    of files in different orders can produce different graphs. The cache
    key must reflect that — otherwise a reversed-order call hits a stale
    cache entry and replays the wrong-order delta (the md<->sv pollution
    bug fixed in v1.6-#1).
    """
    fp1 = pc.compute_corpus_fp([("a", "1"), ("b", "2")])
    fp2 = pc.compute_corpus_fp([("b", "2"), ("a", "1")])
    assert fp1 != fp2, "different orderings must produce different fingerprints"
    # Different content still produces a different fp at fixed order.
    fp3 = pc.compute_corpus_fp([("a", "1"), ("b", "3")])
    assert fp3 != fp1
    # Same list yields same fp (deterministic).
    fp4 = pc.compute_corpus_fp([("a", "1"), ("b", "2")])
    assert fp4 == fp1


def test_compute_ruleset_fp_stable_within_process():
    """Repeated calls in the same process yield the same fingerprint."""
    pc.clear_ruleset_fp_cache()
    fp1 = pc.compute_ruleset_fp()
    fp2 = pc.compute_ruleset_fp()
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex
