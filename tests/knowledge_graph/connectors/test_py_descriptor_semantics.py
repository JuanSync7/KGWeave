"""PyDescriptorSemanticsConnector (v1.8-#4) — tag descriptor-protocol
classes with ``payload.semantic_role = "descriptor"``.

Detection rule: a ``PyClass`` qualifies as a descriptor when at least
one of its direct ``PyFunction`` children is named ``__get__``. The
companion ``__set__`` / ``__delete__`` are not required (Python's
non-data-descriptor variant). Classes lacking ``__get__`` are not
tagged, even if they define other descriptor-adjacent dunders.

Precedence vs PyDecoratorSemanticsConnector: ``semantic_role`` is a
single-valued payload field. Descriptor detection is structural
(implied by method shape) while ``@dataclass`` is explicit (the user
typed it). The decorator connector runs first; the descriptor
connector only writes ``semantic_role`` if it is currently unset —
explicit decorator promotion wins.
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
def _register_py_descriptor_connector() -> None:
    """Register :class:`PyDescriptorSemanticsConnector` once per module.

    The registry is same-class idempotent (v1.5-#5).
    """
    from knowledge_graph.connectors.py_descriptor_semantics import (
        PyDescriptorSemanticsConnector,
    )

    register_connector(PyDescriptorSemanticsConnector())


def _semantic_role(store, name: str) -> str | None:
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyClass'"
        " AND n.name=$name RETURN n.payload AS p",
        {"name": name},
    )
    assert res.rows, f"PyClass {name!r} not found"
    payload = json.loads(res.rows[0]["p"])
    return payload.get("payload", {}).get("semantic_role")


def _run(store, fixture: str) -> None:
    extract(
        store,
        source="py",
        corpus="desc",
        paths=[FIXTURE_DIR / fixture],
    )
    run_connectors(store, only=["py-descriptor-semantics"])


def test_get_only_class_tagged_as_descriptor(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "descriptor_get_only.py")
        assert _semantic_role(store, "ReadOnlyDescriptor") == "descriptor"
    finally:
        store.close()


def test_full_data_descriptor_tagged_as_descriptor(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "descriptor_full.py")
        assert _semantic_role(store, "FullDescriptor") == "descriptor"
    finally:
        store.close()


def test_class_without_get_method_not_tagged(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "not_descriptor.py")
        assert _semantic_role(store, "Plain") is None
        # SetOnly defines __set__ but no __get__ — must NOT be tagged.
        assert _semantic_role(store, "SetOnly") is None
    finally:
        store.close()


def test_decorator_role_takes_precedence_over_descriptor(tmp_path: Path) -> None:
    """A ``@dataclass`` that also implements ``__get__`` keeps
    ``semantic_role='dataclass'``.

    Precedence policy (charter conflict-avoidance note): explicit
    decorator wins over structural descriptor detection. The decorator
    connector must run first; the descriptor connector then sees
    ``semantic_role`` already set and leaves it.
    """
    from knowledge_graph.connectors.py_decorator_semantics import (
        PyDecoratorSemanticsConnector,
    )

    register_connector(PyDecoratorSemanticsConnector())
    fixture = tmp_path / "dc_and_desc.py"
    fixture.write_text(
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class Hybrid:\n"
        "    def __get__(self, instance, owner=None):\n"
        "        return 1\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="desc", paths=[fixture])
        run_connectors(
            store,
            only=["py-decorator-semantics", "py-descriptor-semantics"],
        )
        assert _semantic_role(store, "Hybrid") == "dataclass"
    finally:
        store.close()
