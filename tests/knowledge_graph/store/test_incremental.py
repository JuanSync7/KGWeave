"""I6 — incremental merge semantics for the SV extract path.

These tests use a small two-file fixture (not the full 11-file corpus) so
they run in seconds rather than minutes. The arithmetic invariants are
corpus-size-independent.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from knowledge_graph.builders.sv import build_and_store, extract
from knowledge_graph.store import KGStore
from knowledge_graph.store.schema import REL_TABLES


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


SMALL_FIXTURES = ("fifo_pkg.sv", "fifo_if.sv")


def _table_counts(store) -> dict[str, int]:
    """Return ``{table_name: row_count}`` for every node + rel table."""
    counts: dict[str, int] = {}
    counts["Origin"] = store.conn.execute(
        "MATCH (o:Origin) RETURN count(o)"
    ).get_next()[0]
    counts["Node"] = store.conn.execute(
        "MATCH (n:Node) RETURN count(n)"
    ).get_next()[0]
    for name, _ddl in REL_TABLES:
        res = store.conn.execute(f"MATCH ()-[r:{name}]->() RETURN count(r)")
        counts[name] = res.get_next()[0]
    return counts


def _node_ids_for_origin(store, origin_id: str) -> set[str]:
    res = store.conn.execute(
        "MATCH (n:Node) WHERE n.origin_id = $oid RETURN n.id",
        {"oid": origin_id},
    )
    out: set[str] = set()
    while res.has_next():
        out.add(res.get_next()[0])
    return out


def _origin_ids(store) -> set[str]:
    res = store.conn.execute("MATCH (o:Origin) RETURN o.id")
    out: set[str] = set()
    while res.has_next():
        out.add(res.get_next()[0])
    return out


@pytest.fixture()
def small_corpus(tmp_path: Path, sv_fixture_dir: Path) -> list[Path]:
    """Copy two SV fixtures into a writable tmp dir so tests can mutate them."""
    dest = tmp_path / "corpus"
    dest.mkdir()
    copied: list[Path] = []
    for name in SMALL_FIXTURES:
        src = sv_fixture_dir / name
        dst = dest / name
        shutil.copyfile(src, dst)
        copied.append(dst)
    return copied


@pytest.fixture()
def sv_fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "sv"


# --------------------------------------------------------------------------
# I6.1 — double extract on unchanged corpus is a no-op
# --------------------------------------------------------------------------


def test_double_extract_unchanged_corpus_is_noop(tmp_path, small_corpus):
    """Re-extracting an unchanged corpus produces zero deltas on every table."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    extract(store, small_corpus, corpus="i6")
    before = _table_counts(store)
    origins_before = _origin_ids(store)

    _g, _o, stats = extract(store, small_corpus, corpus="i6")
    after = _table_counts(store)
    origins_after = _origin_ids(store)

    assert after == before, f"counts changed: {before} -> {after}"
    assert origins_after == origins_before, "origin ids drifted on re-extract"
    assert stats.touched_paths == [], "unchanged corpus should touch nothing"
    assert len(stats.unchanged_paths) == len(small_corpus)


# --------------------------------------------------------------------------
# I6.2 — touch ONE file → replaces only its subtree
# --------------------------------------------------------------------------


def test_change_one_file_replaces_only_its_subtree(tmp_path, small_corpus):
    """Mutating one file: that file's subtree is replaced; others are untouched."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    _g, origins_first, _s = extract(store, small_corpus, corpus="i6")

    # Snapshot: which file we'll mutate vs leave alone.
    touched_path = next(p for p in small_corpus if p.name == "fifo_if.sv")
    untouched_path = next(p for p in small_corpus if p.name == "fifo_pkg.sv")
    touched_origin_before = origins_first[touched_path.stem]
    untouched_origin_before = origins_first[untouched_path.stem]
    untouched_node_ids_before = _node_ids_for_origin(store, untouched_origin_before.id)
    assert untouched_node_ids_before, "fifo_pkg.sv should yield nodes"
    touched_node_ids_before = _node_ids_for_origin(store, touched_origin_before.id)
    assert touched_node_ids_before, "fifo_if.sv should yield nodes"

    # Mutate the touched file (append a benign comment).
    touched_path.write_text(touched_path.read_text() + "\n// comment\n")

    _g2, origins_after, stats = extract(store, small_corpus, corpus="i6")

    # (a) touched file's old origin is gone, new origin in its place.
    touched_origin_after = origins_after[touched_path.stem]
    assert touched_origin_after.id != touched_origin_before.id
    surviving = _origin_ids(store)
    assert touched_origin_before.id not in surviving, "old origin not deleted"
    assert touched_origin_after.id in surviving

    # (b) every old node that pointed at the old origin is gone.
    assert _node_ids_for_origin(store, touched_origin_before.id) == set()

    # (c) untouched file's origin id is stable AND its node ids are stable.
    untouched_origin_after = origins_after[untouched_path.stem]
    assert untouched_origin_after.id == untouched_origin_before.id
    untouched_node_ids_after = _node_ids_for_origin(store, untouched_origin_before.id)
    assert untouched_node_ids_after == untouched_node_ids_before

    # (d) stats agree.
    assert str(touched_path.resolve()) in stats.touched_paths
    assert str(untouched_path.resolve()) in stats.unchanged_paths


# --------------------------------------------------------------------------
# I6.3 — unchanged file's origin id is stable across a sibling re-extract
# --------------------------------------------------------------------------


def test_unchanged_file_origin_id_stable(tmp_path, small_corpus):
    """When file A changes, file B's origin id is unchanged."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    _g, origins_first, _s = extract(store, small_corpus, corpus="i6")
    untouched = next(p for p in small_corpus if p.name == "fifo_pkg.sv")
    touched = next(p for p in small_corpus if p.name == "fifo_if.sv")
    untouched_id_before = origins_first[untouched.stem].id

    touched.write_text(touched.read_text() + "\n// noop\n")
    _g2, origins_after, _s2 = extract(store, small_corpus, corpus="i6")
    assert origins_after[untouched.stem].id == untouched_id_before


# --------------------------------------------------------------------------
# Ralph loop additions
# --------------------------------------------------------------------------


def test_new_file_added_between_extracts(tmp_path, small_corpus):
    """A newly-added path is snapshotted and written; existing files survive."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    extract(store, small_corpus, corpus="i6")
    counts_before = _table_counts(store)

    new_file = small_corpus[0].parent / "new_mod.sv"
    new_file.write_text("module new_mod; endmodule\n")
    paths2 = small_corpus + [new_file]
    _g, origins, stats = extract(store, paths2, corpus="i6")

    assert str(new_file.resolve()) in stats.touched_paths
    assert "new_mod" in origins
    counts_after = _table_counts(store)
    assert counts_after["Origin"] == counts_before["Origin"] + 1
    assert counts_after["Node"] > counts_before["Node"]


def test_file_deletion_swept_when_prune_true(tmp_path, small_corpus):
    """With ``prune=True``, dropped paths' origins + nodes are swept."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    _g, origins, _s = extract(store, small_corpus, corpus="i6")
    dropped = next(p for p in small_corpus if p.name == "fifo_if.sv")
    dropped_oid = origins[dropped.stem].id
    kept = [p for p in small_corpus if p is not dropped]

    _g2, _o2, stats = extract(store, kept, corpus="i6", prune=True)
    assert str(dropped.resolve()) in stats.deleted_paths
    assert dropped_oid not in _origin_ids(store)
    assert _node_ids_for_origin(store, dropped_oid) == set()


def test_file_deletion_not_swept_when_prune_false(tmp_path, small_corpus):
    """Default (``prune=False``): dropped paths' origins remain."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    _g, origins, _s = extract(store, small_corpus, corpus="i6")
    dropped = next(p for p in small_corpus if p.name == "fifo_if.sv")
    dropped_oid = origins[dropped.stem].id
    kept = [p for p in small_corpus if p is not dropped]

    extract(store, kept, corpus="i6")  # prune defaults to False
    assert dropped_oid in _origin_ids(store)


def test_cross_corpus_isolation(tmp_path, small_corpus):
    """Re-extracting corpus B leaves corpus A's nodes alone.

    Note: ``:Origin.id`` is keyed on ``(uri, sha)`` only — corpus is a
    *property* of the origin row, not part of its identity. Two corpora
    extracting the same on-disk file share one origin row. The isolation
    guarantee here is that re-extracting under corpus B with unchanged
    files does not delete anything (find_current_origin scopes the lookup
    by ``(uri, source, corpus)``, but since the SHA matches, no
    delete_origin_subtree call fires).
    """
    store = KGStore.open(tmp_path / "kg.kuzu")
    _g, origins_a, _s = extract(store, small_corpus, corpus="A")
    counts_a_before = _table_counts(store)
    a_origin_ids = {ref.id for ref in origins_a.values()}
    # Re-extract under a different corpus name on the same on-disk content.
    # The (uri, source='sv', corpus='B') triple has no existing origin yet,
    # so extract will snapshot — but the underlying origin id is
    # (uri, sha)-derived so the MERGE upserts the same row (potentially
    # rewriting its corpus property). Either way: A's origin ids must still
    # exist and A's nodes must still exist.
    extract(store, small_corpus, corpus="B")
    counts_after = _table_counts(store)
    surviving = _origin_ids(store)
    assert a_origin_ids.issubset(surviving)
    # Node + edge counts must not shrink (no deletes happened).
    for k, v in counts_a_before.items():
        assert counts_after[k] >= v, f"corpus B re-extract shrunk table {k}"


def test_bytewise_change_triggers_full_subtree_replace(tmp_path, small_corpus):
    """Reordering bytes (different sha, same semantics) triggers replacement."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    _g, origins, _s = extract(store, small_corpus, corpus="i6")
    target = small_corpus[0]
    old_id = origins[target.stem].id
    # Append a no-op blank line — sha changes, semantics don't.
    target.write_bytes(target.read_bytes() + b"\n")
    _g2, origins_after, stats = extract(store, small_corpus, corpus="i6")
    assert origins_after[target.stem].id != old_id
    assert str(target.resolve()) in stats.touched_paths
    assert old_id not in _origin_ids(store)


def test_extract_after_close_and_reopen(tmp_path, small_corpus):
    """State persists across close/reopen; re-extract on reopened store is no-op."""
    db_path = tmp_path / "kg.kuzu"
    store = KGStore.open(db_path)
    extract(store, small_corpus, corpus="i6")
    counts_before = _table_counts(store)
    store.close()
    # Reopen.
    store2 = KGStore.open(db_path)
    try:
        counts_reopened = _table_counts(store2)
        assert counts_reopened == counts_before
        _g, _o, stats = extract(store2, small_corpus, corpus="i6")
        assert stats.touched_paths == []
        assert _table_counts(store2) == counts_before
    finally:
        store2.close()


# --------------------------------------------------------------------------
# Performance sanity (informational; asserted loosely).
# --------------------------------------------------------------------------


def test_single_file_touch_is_faster_than_initial_extract(tmp_path, small_corpus):
    """One-file touch re-extract writes strictly fewer rows than initial extract."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    t0 = time.perf_counter()
    _g, _o, s0 = extract(store, small_corpus, corpus="i6perf")
    full_time = time.perf_counter() - t0
    initial_nodes_written = s0.write_stats.nodes_written

    target = small_corpus[0]
    target.write_text(target.read_text() + "\n// poke\n")

    t1 = time.perf_counter()
    _g2, _o2, s1 = extract(store, small_corpus, corpus="i6perf")
    touch_time = time.perf_counter() - t1

    touched_nodes_written = s1.write_stats.nodes_written
    # The write-side must shrink to one file's subgraph.
    assert touched_nodes_written < initial_nodes_written
    # Wall-time may be dominated by build_kg (whole-corpus elaboration);
    # we only sanity-check it isn't dramatically worse.
    assert touch_time < full_time * 3, (
        f"touch re-extract took {touch_time:.2f}s vs full {full_time:.2f}s"
    )
