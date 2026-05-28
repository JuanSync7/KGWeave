"""PyPropertyDescriptorConnector (v1.15-#4) — tag ``@property`` and
``@functools.cached_property`` methods (including aliased imports) with
``payload.semantic_role = "property-descriptor"`` on ``PyFunction``.

The consumer class is NOT tagged — only the descriptor function. Uses
the alias-aware decorator-resolution path established by v1.8-#1.
Precedence: this connector only writes ``semantic_role`` when it is
currently unset on the PyFunction.
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
def _register_py_property_descriptor_connector() -> None:
    """Register :class:`PyPropertyDescriptorConnector` once per module."""
    from knowledge_graph.connectors.py_property_descriptor import (
        PyPropertyDescriptorConnector,
    )

    register_connector(PyPropertyDescriptorConnector())


def _semantic_role(store, name: str) -> str | None:
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyFunction'"
        " AND n.name=$name RETURN n.payload AS p",
        {"name": name},
    )
    assert res.rows, f"PyFunction {name!r} not found"
    payload = json.loads(res.rows[0]["p"])
    return payload.get("payload", {}).get("semantic_role")


def _run(store, fixture: str) -> None:
    extract(
        store,
        source="py",
        corpus="propertydesc",
        paths=[FIXTURE_DIR / fixture],
    )
    run_connectors(store, only=["py-property-descriptor"])


def test_property_basic_tagged(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "property_descriptor_basic.py")
        assert _semantic_role(store, "value") == "property-descriptor"
    finally:
        store.close()


def test_property_cached_tagged(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "property_descriptor_cached.py")
        assert _semantic_role(store, "value") == "property-descriptor"
    finally:
        store.close()


def test_property_aliased_tagged(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "property_descriptor_aliased.py")
        assert _semantic_role(store, "value") == "property-descriptor"
    finally:
        store.close()


def test_non_property_decorators_not_tagged(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "property_descriptor_negative.py")
        assert _semantic_role(store, "s") is None
        assert _semantic_role(store, "c") is None
        assert _semantic_role(store, "plain") is None
    finally:
        store.close()
