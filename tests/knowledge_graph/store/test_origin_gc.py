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
    store, *, oid: str, source: str = "sv", corpus: str = "c", uri: str = "/no/file"
) -> str:
    """Create an Origin row with no child Nodes — a synthetic orphan."""
    store.conn.execute(
        """
        CREATE (o:Origin {
            id: $id, uri: $uri, sha256: 'deadbeef', content: '',
            byte_length: 0, source: $source, corpus: $corpus, lang: ''
        })
        """,
        {"id": oid, "uri": uri, "source": source, "corpus": corpus},
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
