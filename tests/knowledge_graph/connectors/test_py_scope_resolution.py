"""PyScopeResolutionConnector — classify ``PyLambda.captures`` against
per-file lexical scopes (v1.8-#3).

For each capture name on a ``PyLambda`` payload, the connector emits a
``captures_resolved: list[dict]`` parallel structure whose entries take
the shape ``{"name": <str>, "kind": <classification>}`` with
``kind`` in the closed set::

    {"local-in-enclosing", "module-level", "builtin", "unresolved"}

Scope index is built per-file (per ``origin_id``) by re-parsing the
Origin content with libcst. Walker stays pure: this connector reads
the lambda payload back, classifies, and writes ``captures_resolved``
into the same payload JSON. Original ``captures`` is preserved for
back-compat.

Cross-file resolution is OUT OF SCOPE (queued for v1.9).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_graph import (
    cypher,
    extract,
    open_store,
    register_connector,
    run_connectors,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "py"


@pytest.fixture(scope="module", autouse=True)
def _register_py_scope_resolution_connector() -> None:
    """Register :class:`PyScopeResolutionConnector` once per module.

    The registry is same-class idempotent (v1.5-#5), so re-registering
    across test modules in the same session is a no-op.
    """
    from knowledge_graph.connectors.py_scope_resolution import (
        PyScopeResolutionConnector,
    )

    register_connector(PyScopeResolutionConnector())


def _all_lambda_resolutions(store) -> list[list[dict]]:
    """Return every PyLambda's ``captures_resolved`` list, source order."""
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyLambda' "
        "RETURN n.payload AS p, n.start_offset AS s ORDER BY s",
        {},
    )
    out: list[list[dict]] = []
    for row in res.rows:
        payload = json.loads(row["p"])
        inner = payload.get("payload", {})
        out.append(inner.get("captures_resolved", []))
    return out


def _run(store, fixture: str) -> None:
    extract(
        store,
        source="py",
        corpus="scoperes",
        paths=[FIXTURE_DIR / fixture],
    )
    run_connectors(store, only=["py-scope-resolution"])


def _by_name(entries: list[dict]) -> dict[str, str]:
    return {e["name"]: e["kind"] for e in entries}


def test_closure_local_capture_classified_local_in_enclosing(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "lambda_closure_locals.py")
        all_caps = _all_lambda_resolutions(store)
        assert len(all_caps) == 1
        mapping = _by_name(all_caps[0])
        assert mapping == {"y": "local-in-enclosing"}
    finally:
        store.close()


def test_module_level_capture_classified_module_level(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "lambda_module_level.py")
        all_caps = _all_lambda_resolutions(store)
        assert len(all_caps) == 1
        mapping = _by_name(all_caps[0])
        assert mapping == {"foo": "module-level"}
    finally:
        store.close()


def test_builtin_capture_classified_builtin(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "lambda_builtin.py")
        all_caps = _all_lambda_resolutions(store)
        assert len(all_caps) == 1
        mapping = _by_name(all_caps[0])
        # ``list`` is also a captured builtin reference, but the walker
        # records every loaded Name not bound as a param. Assert the
        # documented names at minimum.
        assert mapping["len"] == "builtin"
        assert mapping["range"] == "builtin"
    finally:
        store.close()


def test_unbound_capture_classified_unresolved(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "lambda_unresolved.py")
        all_caps = _all_lambda_resolutions(store)
        assert len(all_caps) == 1
        mapping = _by_name(all_caps[0])
        assert mapping == {"mystery": "unresolved"}
    finally:
        store.close()


def test_nonlocal_promoted_name_classified_local_in_enclosing(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "lambda_nonlocal.py")
        all_caps = _all_lambda_resolutions(store)
        assert len(all_caps) == 1
        mapping = _by_name(all_caps[0])
        assert mapping == {"x": "local-in-enclosing"}
    finally:
        store.close()


def test_walrus_target_classified_local_in_enclosing(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "lambda_walrus.py")
        all_caps = _all_lambda_resolutions(store)
        # Two lambdas; only the first captures ``cached``.
        assert len(all_caps) == 2
        first = _by_name(all_caps[0])
        assert first == {"cached": "local-in-enclosing"}
        # The second lambda (``lambda x: x``) has no captures.
        assert all_caps[1] == []
    finally:
        store.close()
