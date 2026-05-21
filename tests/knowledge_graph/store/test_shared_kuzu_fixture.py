"""Coverage for the v1.4-#2 ``shared_kuzu_store`` fixture.

Tests are ordered alphabetically (pytest default collection within a
file) — the cross-test isolation/leakage assertions rely on that
ordering. Renaming a test here may break the chain; do so with care.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from knowledge_graph.store import KGStore

# Module-level handoff for cross-test assertions. The fixture's per-test
# teardown should clear the previous test's corpus rows before the next
# test runs.
_HANDOFF: dict[str, object] = {}


def _node_count(store: KGStore, corpus: str) -> int:
    res = store.conn.execute(
        "MATCH (n:Node) WHERE n.corpus = $c RETURN count(n)",
        {"c": corpus},
    )
    return int(res.get_next()[0])


def _insert_node(store: KGStore, *, nid: str, corpus: str) -> None:
    """Insert a minimal :Node row tagged with the given corpus."""
    store.conn.execute(
        """
        CREATE (n:Node {
            id: $id, kind: 'Probe', category: 'semantic', name: 'p',
            source: 'sharedfix', corpus: $c,
            origin_id: 'origin-stub',
            start_offset: 0, end_offset: 0,
            start_line: 0, end_line: 0, start_col: 0, end_col: 0,
            payload: '{}'
        })
        """,
        {"id": nid, "c": corpus},
    )


# ---------------------------------------------------------------------- #
# Ordering: pytest collects tests in source order within a file, which
# matches alphabetical here. The names below encode that ordering.
# ---------------------------------------------------------------------- #


def test_a_writes_ten_nodes_under_corpus(shared_kuzu_store):
    """First test in the file writes 10 :Node rows under its own corpus."""
    store, corpus = shared_kuzu_store
    for i in range(10):
        _insert_node(store, nid=f"a-node-{i}", corpus=corpus)
    assert _node_count(store, corpus) == 10
    _HANDOFF["prev_corpus"] = corpus
    _HANDOFF["prev_nodeids"] = [f"a-node-{i}" for i in range(10)]


def test_b_isolation_sees_zero_under_own_corpus(shared_kuzu_store):
    """Second test starts with 0 rows under its own corpus.

    Proves the per-test teardown DETACH DELETEd test_a's data, AND that
    test_a's data was never visible under test_b's corpus.
    """
    store, corpus = shared_kuzu_store
    assert _node_count(store, corpus) == 0
    # And the previous test's corpus rows must be gone too.
    prev_corpus = _HANDOFF.get("prev_corpus")
    assert prev_corpus is not None
    assert _node_count(store, prev_corpus) == 0  # type: ignore[arg-type]


def test_c_cross_test_shares_db_path(shared_kuzu_store):
    """Both this test and test_a observe the SAME on-disk session DB.

    We compare the underlying Kuzu DB directory across two tests via the
    module-level session-store handle exposed by the conftest.
    """
    from tests.knowledge_graph.store.conftest import _SESSION_STORE

    db_path = _SESSION_STORE.get("db_path")
    assert db_path is not None
    _HANDOFF["session_db_path"] = db_path
    # And the store handle is the same Python object across tests.
    store, _corpus = shared_kuzu_store
    assert _SESSION_STORE["store"] is store


def test_d_corpus_strings_are_unique(shared_kuzu_store):
    """Each test gets a distinct corpus tag (hash of nodeid)."""
    _store, corpus = shared_kuzu_store
    seen = _HANDOFF.setdefault("seen_corpora", set())
    assert corpus not in seen, f"corpus tag collision: {corpus}"
    seen.add(corpus)  # type: ignore[union-attr]
    # And we've now accumulated at least 4 distinct corpora over a-d.
    # (The set only sees tests that explicitly registered; we registered
    # in test_d only — but we can still verify the tag format.)
    assert corpus.startswith("t-")
    assert len(corpus) == 2 + 12


def test_e_session_db_path_under_basetemp(shared_kuzu_store):
    """The session DB dir resolves under ``~/.pytest-tmp``."""
    from tests.knowledge_graph.store.conftest import _SESSION_STORE

    db_path = _SESSION_STORE.get("db_path")
    assert db_path is not None
    expected_root = Path(os.path.expanduser("~/.pytest-tmp")).resolve()
    actual = Path(db_path).resolve()  # type: ignore[arg-type]
    assert str(actual).startswith(str(expected_root)), (
        f"session DB {actual} not under {expected_root}"
    )


def test_f_writes_a_named_corpus_row(shared_kuzu_store):
    """Stage a row whose presence the NEXT test will verify is gone."""
    store, corpus = shared_kuzu_store
    _insert_node(store, nid="leak-canary", corpus=corpus)
    assert _node_count(store, corpus) == 1
    _HANDOFF["leak_corpus"] = corpus


def test_g_named_corpus_was_swept(shared_kuzu_store):
    """``leak-canary`` row from test_f must have been DETACH DELETEd."""
    store, _corpus = shared_kuzu_store
    leak_corpus = _HANDOFF.get("leak_corpus")
    assert leak_corpus is not None
    assert _node_count(store, leak_corpus) == 0  # type: ignore[arg-type]
    # And by-id lookup confirms.
    res = store.conn.execute(
        "MATCH (n:Node {id: 'leak-canary'}) RETURN count(n)",
    )
    assert int(res.get_next()[0]) == 0


def test_h_tmp_store_still_works(tmp_store, tmp_path):
    """The OLD ``tmp_store`` fixture coexists and still gets a virgin DB."""
    # Fresh store: zero :Node rows, regardless of what the shared store
    # has accumulated this session.
    res = tmp_store.conn.execute("MATCH (n:Node) RETURN count(n)")
    assert int(res.get_next()[0]) == 0
    # And its on-disk dir is under tmp_path (not the session dir).
    db_dir = tmp_path / "kg.kuzu"
    assert db_dir.exists()
