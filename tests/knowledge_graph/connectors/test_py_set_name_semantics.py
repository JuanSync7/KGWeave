"""PySetNameSemanticsConnector (v1.9-#2) — tag classes that declare
``__set_name__`` with ``payload.semantic_role = "set-name-hook"``.

Detection rule (mirrors v1.8-#4 descriptor connector): a ``PyClass``
qualifies when at least one of its direct ``PyFunction`` children is
named ``__set_name__``. Inheritance is not chased.

Precedence: ``semantic_role`` is single-valued. The descriptor
connector (v1.8-#4) and decorator connector (v1.7-#4) both run first;
this connector only writes when ``semantic_role`` is currently unset.
Decorator-wins / descriptor-wins / set-name-hook is the order from
most-specific to least-specific.
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
def _register_py_set_name_connector() -> None:
    """Register :class:`PySetNameSemanticsConnector` once per module.

    The registry is same-class idempotent (v1.5-#5).
    """
    from knowledge_graph.connectors.py_set_name_semantics import (
        PySetNameSemanticsConnector,
    )
    from knowledge_graph.connectors.py_descriptor_semantics import (
        PyDescriptorSemanticsConnector,
    )

    register_connector(PyDescriptorSemanticsConnector())
    register_connector(PySetNameSemanticsConnector())


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


def _run(store, fixture: str, only: list[str]) -> None:
    extract(
        store,
        source="py",
        corpus="setname",
        paths=[FIXTURE_DIR / fixture],
    )
    run_connectors(store, only=only)


def test_set_name_only_class_tagged_as_set_name_hook(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "set_name_only.py", only=["py-set-name-semantics"])
        assert _semantic_role(store, "TaggedField") == "set-name-hook"
    finally:
        store.close()


def test_descriptor_wins_over_set_name_hook(tmp_path: Path) -> None:
    """A class with both ``__get__`` and ``__set_name__`` MUST keep
    ``semantic_role='descriptor'``.

    Precedence: descriptor (v1.8-#4) is the more specific structural
    role; set-name-hook is the binding-time hook (PEP 487) that often
    accompanies descriptors. Descriptor wins; this connector must skip
    when ``semantic_role`` is already set.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "set_name_with_get.py",
            only=["py-descriptor-semantics", "py-set-name-semantics"],
        )
        assert _semantic_role(store, "DescriptorWithName") == "descriptor"
    finally:
        store.close()


def test_external_set_name_base_does_not_tag_subclass(tmp_path: Path) -> None:
    """v1.14-#4: ``class B(ExternalSetName)`` where the base is not in
    the corpus. ``set-name-hook`` runs with ``chase_bases=False`` so
    this would not tag even if the base were in-corpus and declared
    ``__set_name__`` — pinning the negative on the no-chase connector.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "set_name_external_base.py",
            only=["py-set-name-semantics"],
        )
        assert _semantic_role(store, "B") is None
    finally:
        store.close()


def test_class_without_set_name_method_not_tagged(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "not_descriptor.py", only=["py-set-name-semantics"])
        assert _semantic_role(store, "Plain") is None
        assert _semantic_role(store, "SetOnly") is None
    finally:
        store.close()
