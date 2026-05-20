"""Origin GC sweep — ``KGStore.prune_orphaned_origins`` + ``extract(gc=True)``.

The replacement-merge path on ``extract()`` deletes the child Nodes of an
Origin but does not address two cases:

* An Origin row that lost its last child for any reason (manual deletes,
  a builder bug, a partial write that materialized an Origin but no Nodes).
* A file removed from the corpus on a subsequent ``extract()`` call —
  closed when the caller opts in via ``gc=True``.

``prune_orphaned_origins`` and ``extract(..., gc=True)`` together close
both gaps.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from knowledge_graph import open_store, prune_orphaned_origins
from knowledge_graph.builders.sv import extract
from knowledge_graph.builders.sv.writer import ExtractStats
from knowledge_graph.store import KGStore


SMALL_FIXTURES = ("fifo_pkg.sv", "fifo_if.sv")


@pytest.fixture()
def sv_fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "sv"


@pytest.fixture()
def small_corpus(tmp_path: Path, sv_fixture_dir: Path) -> list[Path]:
    dest = tmp_path / "corpus"
    dest.mkdir()
    out: list[Path] = []
    for name in SMALL_FIXTURES:
        dst = dest / name
        shutil.copyfile(sv_fixture_dir / name, dst)
        out.append(dst)
    return out


def _origin_ids(store, *, source: str | None = None, corpus: str | None = None) -> set[str]:
    cypher = "MATCH (o:Origin)"
    where: list[str] = []
    params: dict = {}
    if source is not None:
        where.append("o.source = $source")
        params["source"] = source
    if corpus is not None:
        where.append("o.corpus = $corpus")
        params["corpus"] = corpus
    if where:
        cypher += " WHERE " + " AND ".join(where)
    cypher += " RETURN o.id"
    res = store.conn.execute(cypher, params) if params else store.conn.execute(cypher)
    out: set[str] = set()
    while res.has_next():
        out.add(res.get_next()[0])
    return out


def _insert_bare_origin(
    store,
    *,
    oid: str,
    source: str = "sv",
    corpus: str = "c",
    uri: str = "/no/file",
    sha256: str = "deadbeef",
) -> str:
    """Create an Origin row with no child Nodes — a synthetic orphan."""
    store.conn.execute(
        """
        CREATE (o:Origin {
            id: $id, uri: $uri, sha256: $sha, content: '',
            byte_length: 0, source: $source, corpus: $corpus, lang: ''
        })
        """,
        {
            "id": oid,
            "uri": uri,
            "source": source,
            "corpus": corpus,
            "sha": sha256,
        },
    )
    return oid


# --------------------------------------------------------------------------
# Direct method tests
# --------------------------------------------------------------------------


def test_prune_clean_store_returns_zero(tmp_path):
    """Idempotency: a clean store reports zero pruned rows."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        n = store.prune_orphaned_origins()
        assert n == 0
        # Second call still zero.
        assert store.prune_orphaned_origins() == 0
    finally:
        store.close()


def test_prune_single_orphan(tmp_path):
    """A lone Origin with no child Node is deleted; the count is 1."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        _insert_bare_origin(store, oid="orphan-1")
        assert "orphan-1" in _origin_ids(store)
        n = store.prune_orphaned_origins()
        assert n == 1
        assert "orphan-1" not in _origin_ids(store)
        # Idempotent re-call.
        assert store.prune_orphaned_origins() == 0
    finally:
        store.close()


def test_prune_keeps_live_origins(tmp_path, small_corpus):
    """Origins that still own Nodes survive; only orphans are dropped."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        extract(store, small_corpus, corpus="c")
        live_ids = _origin_ids(store)
        assert live_ids, "expected at least one live origin"
        _insert_bare_origin(store, oid="orphan-x", corpus="c")
        n = store.prune_orphaned_origins()
        assert n == 1
        assert _origin_ids(store) == live_ids
    finally:
        store.close()


def test_prune_scopes_by_source_and_corpus(tmp_path):
    """``source`` / ``corpus`` filters only sweep matching orphans."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        _insert_bare_origin(store, oid="a", source="sv", corpus="alpha")
        _insert_bare_origin(store, oid="b", source="sv", corpus="beta")
        _insert_bare_origin(store, oid="c", source="py", corpus="alpha")

        # Scope to corpus='alpha' across all sources.
        n = store.prune_orphaned_origins(corpus="alpha")
        assert n == 2
        ids = _origin_ids(store)
        assert ids == {"b"}

        # Reset and re-create.
        _insert_bare_origin(store, oid="a", source="sv", corpus="alpha")
        _insert_bare_origin(store, oid="c", source="py", corpus="alpha")
        # Scope to source='py'.
        n = store.prune_orphaned_origins(source="py")
        assert n == 1
        assert _origin_ids(store) == {"a", "b"}
    finally:
        store.close()


def test_prune_facade_export(tmp_path):
    """``prune_orphaned_origins`` is reachable through the package facade."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _insert_bare_origin(store, oid="orphan-facade")
        n = prune_orphaned_origins(store)
        assert n == 1
        assert prune_orphaned_origins(store) == 0
    finally:
        store.close()


# --------------------------------------------------------------------------
# Builder-isolation (I7) extension: cross-builder gc=True must not touch peers.
# --------------------------------------------------------------------------


def test_gc_does_not_touch_other_builder_origins(tmp_path, small_corpus):
    """Builder A's ``gc=True`` sweep leaves builder B's orphan origins alone.

    Even an orphan from another source is out of scope for the targeted call.
    """
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        # Builder B's orphan.
        _insert_bare_origin(store, oid="b-orphan", source="otherb", corpus="anyc")
        # Builder A populates real content.
        extract(store, small_corpus, corpus="cA", gc=True)
        # The "otherb" orphan must survive the sv gc.
        assert "b-orphan" in _origin_ids(store)
        # A targeted facade-level gc against otherb does sweep it.
        n = store.prune_orphaned_origins(source="otherb")
        assert n == 1
        assert "b-orphan" not in _origin_ids(store)
    finally:
        store.close()


# --------------------------------------------------------------------------
# extract(gc=True) — removed-file sweep (full-corpus claim).
# --------------------------------------------------------------------------


def test_extract_gc_removes_dropped_file_subtree(tmp_path, small_corpus):
    """A file dropped from the input set has its Origin + subtree deleted
    when the caller invokes ``extract(gc=True)``.
    """
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        _g, origins, _s = extract(store, small_corpus, corpus="gc-corpus")
        dropped = next(p for p in small_corpus if p.name == "fifo_if.sv")
        dropped_oid = origins[dropped.stem].id
        kept = [p for p in small_corpus if p is not dropped]

        _g2, _o2, stats = extract(store, kept, corpus="gc-corpus", gc=True)

        ids = _origin_ids(store)
        assert dropped_oid not in ids, "gc=True should sweep dropped file's Origin"
        # The kept origin survives.
        for p in kept:
            assert origins[p.stem].id in ids
        assert str(dropped.resolve()) in stats.deleted_paths
    finally:
        store.close()


def test_extract_gc_idempotent_on_clean_corpus(tmp_path, small_corpus):
    """``extract(gc=True)`` on an unchanged corpus is still a no-op."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        extract(store, small_corpus, corpus="gc-corpus", gc=True)
        ids_before = _origin_ids(store)
        _g, _o, stats = extract(store, small_corpus, corpus="gc-corpus", gc=True)
        ids_after = _origin_ids(store)
        assert ids_after == ids_before
        assert stats.touched_paths == []
        assert stats.deleted_paths == []
    finally:
        store.close()


# --------------------------------------------------------------------------
# v1.3-#4: ExtractStats.gc_pruned exposes Origin-sweep count.
# --------------------------------------------------------------------------


def test_extract_stats_gc_pruned_default_zero():
    """``ExtractStats.gc_pruned`` defaults to 0 and is an ``int``."""
    s = ExtractStats()
    assert s.gc_pruned == 0
    assert isinstance(s.gc_pruned, int)


def test_extract_stats_gc_pruned_field_assignable():
    """``ExtractStats(gc_pruned=5).gc_pruned == 5`` (explicit construction)."""
    s = ExtractStats(gc_pruned=5)
    assert s.gc_pruned == 5
    assert isinstance(s.gc_pruned, int)


def test_extract_gc_false_leaves_gc_pruned_zero(tmp_path, small_corpus):
    """When ``gc=False`` the prune call is skipped — ``gc_pruned`` stays 0."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        # Seed an orphan that WOULD be swept if gc were on.
        _insert_bare_origin(
            store, oid="orphan-skip", source="sv", corpus="gc-corpus"
        )
        _g, _o, stats = extract(store, small_corpus, corpus="gc-corpus")
        assert stats.gc_pruned == 0
        # And the orphan is still there because no sweep ran.
        assert "orphan-skip" in _origin_ids(store)
    finally:
        store.close()


def test_extract_gc_true_no_orphans_reports_zero(tmp_path, small_corpus):
    """``gc=True`` on a corpus with no orphans reports ``gc_pruned == 0``."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        _g, _o, stats = extract(store, small_corpus, corpus="gc-corpus", gc=True)
        assert stats.gc_pruned == 0
        # Re-run: still nothing to sweep.
        _g2, _o2, stats2 = extract(
            store, small_corpus, corpus="gc-corpus", gc=True
        )
        assert stats2.gc_pruned == 0
    finally:
        store.close()


def _seed_in_scope_orphan(store, corpus_paths, *, oid: str, corpus: str) -> None:
    """Insert an orphan that survives ``effective_prune`` so the GC sweep counts it.

    The replacement-merge path inside ``extract`` deletes any Origin in
    ``(source, corpus)`` whose ``uri`` is not part of the new input set
    BEFORE the orphan sweep runs. To stage an orphan that reaches the
    sweep, we must (a) use a uri that *is* in the input set, and (b) use
    the real file's sha256 so the orphan is treated as ``unchanged`` and
    not its subtree-deleted (we also pick an id lexicographically larger
    than any real origin id so ``find_current_origin`` still resolves to
    the real one).
    """
    from knowledge_graph.shared.ids import sha256_bytes

    p = corpus_paths[0]
    _insert_bare_origin(
        store,
        oid=oid,
        source="sv",
        corpus=corpus,
        uri=str(p.resolve()),
        sha256=sha256_bytes(p.read_bytes()),
    )


def test_extract_gc_true_reports_single_orphan_swept(tmp_path, small_corpus):
    """A pre-existing orphan in ``(source, corpus)`` shows up in ``gc_pruned``."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        extract(store, small_corpus, corpus="gc-corpus")
        _seed_in_scope_orphan(
            store, small_corpus, oid="zzzz-orphan-a", corpus="gc-corpus"
        )
        _g, _o, stats = extract(
            store, small_corpus, corpus="gc-corpus", gc=True
        )
        assert stats.gc_pruned == 1
        assert "zzzz-orphan-a" not in _origin_ids(store)
    finally:
        store.close()


def test_extract_gc_true_reports_three_orphans_swept(tmp_path, small_corpus):
    """``gc_pruned`` is the exact number of Origins the sweep deleted (n=3)."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        extract(store, small_corpus, corpus="gc-corpus")
        for oid in ("zzzz-orphan-1", "zzzz-orphan-2", "zzzz-orphan-3"):
            _seed_in_scope_orphan(
                store, small_corpus, oid=oid, corpus="gc-corpus"
            )
        _g, _o, stats = extract(
            store, small_corpus, corpus="gc-corpus", gc=True
        )
        assert stats.gc_pruned == 3
        ids_after = _origin_ids(store)
        for oid in ("zzzz-orphan-1", "zzzz-orphan-2", "zzzz-orphan-3"):
            assert oid not in ids_after
    finally:
        store.close()


def test_extract_gc_pruned_scoped_to_source_corpus(tmp_path, small_corpus):
    """The prune call is scoped — orphans outside ``(source, corpus)`` don't count."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        extract(store, small_corpus, corpus="gc-corpus")
        # In-scope orphan: counted.
        _seed_in_scope_orphan(
            store, small_corpus, oid="zzzz-in-scope", corpus="gc-corpus"
        )
        # Out-of-scope orphans: NOT counted, NOT swept. These can use the
        # default uri because they're outside the (source, corpus) the
        # effective_prune sweep iterates.
        _insert_bare_origin(
            store, oid="other-source", source="md", corpus="gc-corpus"
        )
        _insert_bare_origin(
            store, oid="other-corpus", source="sv", corpus="elsewhere"
        )
        _g, _o, stats = extract(
            store, small_corpus, corpus="gc-corpus", gc=True
        )
        assert stats.gc_pruned == 1
        remaining = _origin_ids(store)
        assert "zzzz-in-scope" not in remaining
        assert "other-source" in remaining
        assert "other-corpus" in remaining
    finally:
        store.close()


def test_extract_gc_pruned_via_no_touched_paths_branch(tmp_path, small_corpus):
    """The early-return branch (no touched paths) also populates ``gc_pruned``.

    Covers the second sweep call-site inside ``extract`` — when the input
    set is unchanged AND ``gc=True``, the function bails before writes but
    must still surface the prune count.
    """
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        extract(store, small_corpus, corpus="gc-corpus")
        _seed_in_scope_orphan(
            store, small_corpus, oid="zzzz-early-1", corpus="gc-corpus"
        )
        _seed_in_scope_orphan(
            store, small_corpus, oid="zzzz-early-2", corpus="gc-corpus"
        )
        _g, _o, stats = extract(
            store, small_corpus, corpus="gc-corpus", gc=True
        )
        assert stats.touched_paths == []
        assert stats.gc_pruned == 2
    finally:
        store.close()
