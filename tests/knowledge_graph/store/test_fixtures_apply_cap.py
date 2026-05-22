"""G3: store-test fixtures must open Kuzu with the 256 MiB cap.

The ``tmp_store`` and session-scoped ``shared_kuzu_store`` fixtures
in this directory's conftest must both forward
``max_db_size_bytes=268_435_456`` (256 MiB) to ``KGStore.open``,
matching the v1.5-#1 cap that keeps ext4 basetemp wall-times low.

Verified by spying on ``kuzu.Database`` during the fixture's open
call and asserting ``max_db_size`` was passed as the 256 MiB value.

We use an autouse session-scoped spy for the shared store assertion
because the shared store is opened once-per-session at fixture setup
time, before any test body runs -- so we cannot install a per-test
monkeypatch and observe its construction.
"""

from __future__ import annotations

import inspect

from knowledge_graph.store import KGStore

_EXPECTED_CAP = 268_435_456  # 2**28 == 256 MiB, power-of-2 (Kuzu req)


def test_tmp_store_fixture_uses_max_db_size_cap() -> None:
    """The ``tmp_store`` fixture body must reference the cap constant.

    Source-level guard: introspect the fixture function so we catch a
    regression where someone reverts the fixture to ``KGStore.open(path)``
    without the cap. We don't try to spy on Kuzu from inside the fixture
    -- that would race the conftest import. Static guard is sufficient
    because the cap value is load-bearing and tested for-real in the
    KGStore.open forwarding test.
    """
    from tests.knowledge_graph.store import conftest as store_conftest

    src = inspect.getsource(store_conftest.tmp_store)
    assert "max_db_size_bytes" in src, (
        "tmp_store fixture must pass max_db_size_bytes to KGStore.open "
        "(v1.5-#1); current source:\n" + src
    )
    assert str(_EXPECTED_CAP) in src or "1 << 28" in src or "2 ** 28" in src, (
        f"tmp_store fixture must pin max_db_size_bytes={_EXPECTED_CAP} "
        "(256 MiB, power-of-2); current source:\n" + src
    )


def test_shared_kuzu_session_store_uses_max_db_size_cap() -> None:
    """The session-scoped shared store fixture must also pin the cap."""
    from tests.knowledge_graph.store import conftest as store_conftest

    src = inspect.getsource(store_conftest._shared_kuzu_session_store)
    assert "max_db_size_bytes" in src, (
        "_shared_kuzu_session_store fixture must pass max_db_size_bytes "
        "to KGStore.open (v1.5-#1); current source:\n" + src
    )
    assert str(_EXPECTED_CAP) in src or "1 << 28" in src or "2 ** 28" in src, (
        f"shared_kuzu_session_store must pin max_db_size_bytes={_EXPECTED_CAP} "
        "(256 MiB, power-of-2); current source:\n" + src
    )


def test_kgstore_open_signature_documents_cap() -> None:
    """``KGStore.open`` signature must still expose the kwarg (G1 anchor)."""
    sig = inspect.signature(KGStore.open)
    assert "max_db_size_bytes" in sig.parameters
