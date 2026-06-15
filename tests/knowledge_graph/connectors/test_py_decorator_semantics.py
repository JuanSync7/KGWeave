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


# ---------------------------------------------------------------------------
# v1.8-#1: alias-aware promotion via per-file import-rename map.
#
# Walker preserves the ``asname`` from ``import x as y`` /
# ``from m import a as b`` on the PyImport payload as
# ``aliases: {local_name: canonical_dotted_name}``. The connector reads
# every PyImport row in the same file as a PyClass/PyFunction, builds
# a per-file map, and rewrites the leading dotted-segment of each
# decorator string THROUGH that map before the closed-table lookup.
# ---------------------------------------------------------------------------


def test_aliased_dataclass_decorator_promotes_through_import_rename(
    tmp_path: Path,
) -> None:
    """``from dataclasses import dataclass as _dc; @_dc`` must promote."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "dataclass_aliased.py")
        assert _semantic_role(store, "AliasedPoint") == "dataclass"
    finally:
        store.close()


def test_aliased_pytest_module_decorator_promotes_through_import_rename(
    tmp_path: Path,
) -> None:
    """``import pytest as pt; @pt.fixture`` must promote."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "pytest_fixture_aliased.py")
        assert _semantic_role(store, "aliased_fixture") == "fixture"
    finally:
        store.close()


def test_aliased_property_decorator_promotes_through_import_rename(
    tmp_path: Path,
) -> None:
    """``from builtins import property as prop; @prop`` must promote."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "property_aliased.py")
        assert _semantic_role(store, "radius") == "property"
    finally:
        store.close()


def test_aliased_cached_property_does_NOT_promote(tmp_path: Path) -> None:
    """``cached_property`` is not in the closed table — alias must not promote.

    Negative control: even though ``@cp`` resolves through the import-
    rename map to ``functools.cached_property``, that canonical name is
    deliberately absent from ``_DECORATOR_ROLE``, so ``semantic_role``
    must stay unset.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "property_aliased.py")
        assert _semantic_role(store, "diameter") is None
    finally:
        store.close()
