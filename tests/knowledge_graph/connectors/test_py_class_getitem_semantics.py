"""PyClassGetitemSemanticsConnector (v1.15-#2) — tag classes that
declare ``__class_getitem__`` with
``payload.semantic_role = "class-getitem-hook"``.

Detection rule (mirrors v1.11-#4 init-subclass-hook connector with
``chase_bases=True``): a ``PyClass`` qualifies when at least one of
its direct ``PyFunction`` children is named ``__class_getitem__``, or
when any of its in-corpus ancestors along the declared ``bases``
chain qualifies.

Precedence: ``semantic_role`` is single-valued. Decorator, descriptor,
set-name-hook, and init-subclass-hook connectors all run more
specifically; this connector only writes when ``semantic_role`` is
currently unset.
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
def _register_py_class_getitem_connector() -> None:
    """Register :class:`PyClassGetitemSemanticsConnector` once per module.

    The registry is same-class idempotent (v1.5-#5).
    """
    from knowledge_graph.connectors.py_class_getitem_semantics import (
        PyClassGetitemSemanticsConnector,
    )
    from knowledge_graph.connectors.py_descriptor_semantics import (
        PyDescriptorSemanticsConnector,
    )

    register_connector(PyDescriptorSemanticsConnector())
    register_connector(PyClassGetitemSemanticsConnector())


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
        corpus="classgetitem",
        paths=[FIXTURE_DIR / fixture],
    )
    run_connectors(store, only=only)


def test_class_getitem_only_class_tagged_as_class_getitem_hook(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "class_getitem_only.py",
            only=["py-class-getitem-semantics"],
        )
        assert _semantic_role(store, "TaggedBase") == "class-getitem-hook"
    finally:
        store.close()


def test_descriptor_wins_over_class_getitem_hook(tmp_path: Path) -> None:
    """A class with both ``__get__`` and ``__class_getitem__`` MUST keep
    ``semantic_role='descriptor'``.

    Precedence: descriptor (v1.8-#4) is the more specific structural
    role; class-getitem-hook is the subscription hook (PEP 560).
    Descriptor wins; this connector must skip when ``semantic_role`` is
    already set.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "class_getitem_with_get.py",
            only=[
                "py-descriptor-semantics",
                "py-class-getitem-semantics",
            ],
        )
        assert (
            _semantic_role(store, "DescriptorWithClassGetitem")
            == "descriptor"
        )
    finally:
        store.close()


def test_class_getitem_inheritance_single_hop_tags_subclass(
    tmp_path: Path,
) -> None:
    """v1.15-#2 inheritance chasing: ``Base`` declares
    ``__class_getitem__``; ``Sub(Base)`` inherits it. Both must be
    tagged ``semantic_role='class-getitem-hook'`` since this connector
    sets ``chase_bases=True``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "class_getitem_inherited.py",
            only=["py-class-getitem-semantics"],
        )
        assert _semantic_role(store, "Base") == "class-getitem-hook"
        assert _semantic_role(store, "Sub") == "class-getitem-hook"
    finally:
        store.close()


def test_class_without_class_getitem_method_not_tagged(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "not_descriptor.py",
            only=["py-class-getitem-semantics"],
        )
        assert _semantic_role(store, "Plain") is None
        assert _semantic_role(store, "SetOnly") is None
    finally:
        store.close()
