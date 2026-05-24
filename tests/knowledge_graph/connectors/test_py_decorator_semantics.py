"""PyDecoratorSemanticsConnector — promote known decorator names to a
``semantic_role`` tag inside PyFunction / PyClass payloads.

v1.7-#4. Walker-pure: the walker records the decorator strings on the
node payload (v1.6-#3 G1); this connector reinterprets three of them at
connector time so the walker stays a pure structural lifter.

Promotion rules (closed set):
  * ``@dataclass`` or ``@dataclasses.dataclass`` → PyClass.semantic_role = "dataclass"
  * ``@pytest.fixture``                          → PyFunction.semantic_role = "fixture"
  * ``@property``                                → PyFunction.semantic_role = "property"

All other decorators (e.g. ``@functools.cache``, ``@staticmethod``)
leave ``semantic_role`` unset.
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
def _register_py_decorator_connector() -> None:
    """Register :class:`PyDecoratorSemanticsConnector` once per module.

    The registry is same-class idempotent (v1.5-#5), so re-registering
    across test modules in the same session is a no-op.
    """
    from knowledge_graph.connectors.py_decorator_semantics import (
        PyDecoratorSemanticsConnector,
    )

    register_connector(PyDecoratorSemanticsConnector())


def _semantic_role(store, name: str) -> str | None:
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.name=$name "
        "RETURN n.payload AS p",
        {"name": name},
    )
    assert res.rows, f"node {name!r} not found"
    payload = json.loads(res.rows[0]["p"])
    return payload.get("payload", {}).get("semantic_role")


def _run(store, fixture: str) -> None:
    extract(
        store,
        source="py",
        corpus="decsem",
        paths=[FIXTURE_DIR / fixture],
    )
    run_connectors(store, only=["py-decorator-semantics"])


def test_dataclass_decorator_promotes_to_dataclass(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "dataclass_basic.py")
        assert _semantic_role(store, "Point") == "dataclass"
    finally:
        store.close()


def test_pytest_fixture_decorator_promotes_to_fixture(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "pytest_fixture_basic.py")
        # Both bare and parametrised @pytest.fixture must promote.
        assert _semantic_role(store, "simple_fixture") == "fixture"
        assert _semantic_role(store, "parametrised_fixture") == "fixture"
    finally:
        store.close()


def test_property_decorator_promotes_to_property(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "property_basic.py")
        assert _semantic_role(store, "radius") == "property"
        assert _semantic_role(store, "diameter") == "property"
    finally:
        store.close()


def test_unknown_decorator_leaves_semantic_role_unset(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "unknown_decorator.py")
        assert _semantic_role(store, "cached_fn") is None
        assert _semantic_role(store, "util") is None
    finally:
        store.close()
