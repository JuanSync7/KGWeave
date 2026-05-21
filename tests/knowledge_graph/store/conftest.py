"""Shared pytest fixtures for store tests.

Kuzu-backed integration tests routinely run 60-120 s on this box because each
test spins a fresh embedded DB, runs a real SV extraction, and re-opens. The
global ``timeout = 60`` guard would trip on these tests by design -- so this
conftest bumps the per-test timeout to 300 s for everything under
``tests/knowledge_graph/store/``. The lower 60 s default still protects the
rest of the suite from sibling-pytest I/O wedges.

Fixtures
========

``tmp_store``
    Per-test fresh ``KGStore``. Use this when a test mutates ``:Meta``, needs
    a virgin schema, exercises store-open semantics, or otherwise relies on
    starting from an empty DB. This is the safe default for any test whose
    behaviour is sensitive to global store state.

``shared_kuzu_store`` (v1.4-#2 prototype)
    Session-scoped shared ``KGStore`` with per-test corpus-namespaced
    isolation. Yields ``(store, corpus)``. Every node/edge the test writes
    MUST be tagged with ``corpus=corpus`` so the per-test teardown can
    ``DETACH DELETE`` only that test's rows.

    DO NOT use ``shared_kuzu_store`` for:
      * tests that touch ``:Meta`` / ``KGWEAVE_SCHEMA_VERSION``
      * tests that exercise ``KGStore.open`` / close / reopen behaviour
      * tests that assume an empty ``:Origin`` / ``:Node`` table

    Those tests must keep using ``tmp_store`` or raw ``KGStore.open(tmp_path
    / "kg.kuzu")``.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Iterator

import pytest

from knowledge_graph.store import KGStore


_log = logging.getLogger(__name__)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Apply a 300 s timeout to every test collected from this directory."""
    here = Path(__file__).resolve().parent
    marker = pytest.mark.timeout(300)
    for item in items:
        try:
            item_path = Path(item.fspath).resolve()
        except (TypeError, ValueError):
            continue
        try:
            item_path.relative_to(here)
        except ValueError:
            continue
        item.add_marker(marker)


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``shared_store`` opt-in marker."""
    config.addinivalue_line(
        "markers",
        "shared_store: test consumes the session-scoped shared_kuzu_store fixture",
    )


@pytest.fixture()
def tmp_store(tmp_path: Path) -> Iterator[KGStore]:
    """Open a fresh KGStore backed by a tmp_path Kuzu directory."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    try:
        yield store
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# v1.4-#2 prototype: session-scoped shared Kuzu DB.                           #
# --------------------------------------------------------------------------- #

# Module-level handle so the shared-fixture tests can introspect session state
# (e.g. assert the DB path is under basetemp) without re-walking pytest's
# fixture cache.
_SESSION_STORE: dict[str, object] = {}


@pytest.fixture(scope="session")
def _shared_kuzu_session_store(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[KGStore]:
    """Session-scoped KGStore.open() backed by a basetemp-rooted dir.

    The DB directory lives under
    ``tmp_path_factory.mktemp("kgweave-session")`` so it inherits the
    ``~/.pytest-tmp`` basetemp redirect from v1.4-#1.
    """
    session_root = tmp_path_factory.mktemp("kgweave-session")
    db_path = session_root / "shared.kuzu"
    store = KGStore.open(db_path)
    _SESSION_STORE["store"] = store
    _SESSION_STORE["db_path"] = db_path
    try:
        yield store
    finally:
        try:
            store.close()
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("shared session store close failed: %s", exc)
        shutil.rmtree(db_path, ignore_errors=True)
        _SESSION_STORE.clear()


def _corpus_for_node(nodeid: str) -> str:
    """Stable, unique-per-test corpus tag derived from the pytest nodeid."""
    digest = hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:12]
    return f"t-{digest}"


@pytest.fixture()
def shared_kuzu_store(
    request: pytest.FixtureRequest, _shared_kuzu_session_store: KGStore
) -> Iterator[tuple[KGStore, str]]:
    """Per-test corpus-namespaced view over the session-shared KGStore.

    Yields ``(store, corpus)``. Tests MUST tag every node/edge they write
    with ``corpus=corpus`` so the teardown DETACH DELETE only sweeps this
    test's rows. The teardown also sweeps any ``:Origin`` rows tagged with
    the same corpus.
    """
    store = _shared_kuzu_session_store
    corpus = _corpus_for_node(request.node.nodeid)
    try:
        yield store, corpus
    finally:
        # Best-effort scoped cleanup. Order: Nodes first (carry corpus),
        # then Origins (also carry corpus). Both via DETACH DELETE so any
        # connecting rels are dropped too. Errors logged, not raised.
        for label in ("Node", "Origin"):
            cypher = f"MATCH (n:{label}) WHERE n.corpus = $c DETACH DELETE n"
            try:
                store.conn.execute(cypher, {"c": corpus})
            except Exception as exc:
                _log.debug(
                    "shared_kuzu_store teardown on %s for corpus=%s: %s",
                    label,
                    corpus,
                    exc,
                )
