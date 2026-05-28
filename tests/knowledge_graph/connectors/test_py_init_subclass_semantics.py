"""PyInitSubclassSemanticsConnector (v1.10-#4) — tag classes that
declare ``__init_subclass__`` with
``payload.semantic_role = "init-subclass-hook"``.

Detection rule (mirrors v1.9-#2 set-name-hook connector): a
``PyClass`` qualifies when at least one of its direct ``PyFunction``
children is named ``__init_subclass__``. Inheritance is not chased.

Precedence: ``semantic_role`` is single-valued. The descriptor
connector (v1.8-#4), decorator connector (v1.7-#4), and set-name-hook
connector (v1.9-#2) all run first; this connector only writes when
``semantic_role`` is currently unset. Decorator / descriptor /
set-name-hook / init-subclass-hook is the order from most-specific to
least-specific.
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
def _register_py_init_subclass_connector() -> None:
    """Register :class:`PyInitSubclassSemanticsConnector` once per module.

    The registry is same-class idempotent (v1.5-#5).
    """
    from knowledge_graph.connectors.py_init_subclass_semantics import (
        PyInitSubclassSemanticsConnector,
    )
    from knowledge_graph.connectors.py_descriptor_semantics import (
        PyDescriptorSemanticsConnector,
    )

    register_connector(PyDescriptorSemanticsConnector())
    register_connector(PyInitSubclassSemanticsConnector())


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
        corpus="initsubclass",
        paths=[FIXTURE_DIR / fixture],
    )
    run_connectors(store, only=only)


def test_init_subclass_only_class_tagged_as_init_subclass_hook(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "init_subclass_only.py",
            only=["py-init-subclass-semantics"],
        )
        assert _semantic_role(store, "TaggedBase") == "init-subclass-hook"
    finally:
        store.close()


def test_descriptor_wins_over_init_subclass_hook(tmp_path: Path) -> None:
    """A class with both ``__get__`` and ``__init_subclass__`` MUST keep
    ``semantic_role='descriptor'``.

    Precedence: descriptor (v1.8-#4) is the more specific structural
    role; init-subclass-hook is the subclass-creation hook (PEP 487).
    Descriptor wins; this connector must skip when ``semantic_role`` is
    already set.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "init_subclass_with_get.py",
            only=[
                "py-descriptor-semantics",
                "py-init-subclass-semantics",
            ],
        )
        assert (
            _semantic_role(store, "DescriptorWithInitSubclass")
            == "descriptor"
        )
    finally:
        store.close()


def test_class_without_init_subclass_method_not_tagged(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "not_descriptor.py",
            only=["py-init-subclass-semantics"],
        )
        assert _semantic_role(store, "Plain") is None
        assert _semantic_role(store, "SetOnly") is None
    finally:
        store.close()


def test_init_subclass_inheritance_single_hop_tags_subclass(
    tmp_path: Path,
) -> None:
    """v1.11-#4 inheritance chasing: ``A`` declares ``__init_subclass__``;
    ``B(A)`` inherits it. Both must be tagged
    ``semantic_role='init-subclass-hook'`` once the helper's
    ``chase_bases`` flag is True for this connector.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "init_subclass_inherited.py",
            only=["py-init-subclass-semantics"],
        )
        assert _semantic_role(store, "A") == "init-subclass-hook"
        assert _semantic_role(store, "B") == "init-subclass-hook"
    finally:
        store.close()


def test_init_subclass_inheritance_multi_hop_tags_full_chain(
    tmp_path: Path,
) -> None:
    """v1.11-#4 inheritance chasing — transitive: ``A`` declares
    ``__init_subclass__``; ``B(A)`` and ``C(B)`` inherit transitively.
    All three must be tagged ``semantic_role='init-subclass-hook'``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "init_subclass_inherited_multi_hop.py",
            only=["py-init-subclass-semantics"],
        )
        assert _semantic_role(store, "A") == "init-subclass-hook"
        assert _semantic_role(store, "B") == "init-subclass-hook"
        assert _semantic_role(store, "C") == "init-subclass-hook"
    finally:
        store.close()


def test_metaclass_init_subclass_tags_class(tmp_path: Path) -> None:
    """v1.14-#2: ``class Klass(metaclass=Meta)`` where ``Meta`` declares
    ``__init_subclass__`` must tag ``Klass`` with
    ``semantic_role='init-subclass-hook'``. ``Meta`` itself directly
    declares the hook and is also tagged.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "init_subclass_metaclass.py",
            only=["py-init-subclass-semantics"],
        )
        assert _semantic_role(store, "Meta") == "init-subclass-hook"
        assert _semantic_role(store, "Klass") == "init-subclass-hook"
    finally:
        store.close()


def test_external_metaclass_does_not_tag_class(tmp_path: Path) -> None:
    """v1.14-#2 negative: when the declared metaclass is not in the
    corpus, the class stays untagged — out-of-corpus metaclasses are
    opaque.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "init_subclass_external_metaclass.py",
            only=["py-init-subclass-semantics"],
        )
        assert _semantic_role(store, "Klass2") is None
    finally:
        store.close()


def test_external_init_subclass_base_does_not_tag_subclass(
    tmp_path: Path,
) -> None:
    """v1.14-#4: ``class B(ExternalHook)`` where the base is not in the
    corpus — chase terminates cleanly; ``B`` stays untagged even though
    this connector has ``chase_bases=True`` (v1.11-#4).
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "init_subclass_external_base.py",
            only=["py-init-subclass-semantics"],
        )
        assert _semantic_role(store, "B") is None
    finally:
        store.close()


def test_descriptor_wins_over_inherited_init_subclass_hook(
    tmp_path: Path,
) -> None:
    """v1.11-#4 precedence with inheritance: ``DescriptorChild`` directly
    declares ``__get__`` AND inherits ``__init_subclass__`` from
    ``HookBase``. Descriptor (v1.8-#4) is the more specific structural
    role and runs first; ``DescriptorChild`` MUST keep
    ``semantic_role='descriptor'`` (the v1.11-#4 inheritance-chasing
    init-subclass connector must not overwrite it).

    ``HookBase`` itself directly declares ``__init_subclass__`` and must
    still be tagged ``'init-subclass-hook'``.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(
            store,
            "init_subclass_inherited_with_get.py",
            only=[
                "py-descriptor-semantics",
                "py-init-subclass-semantics",
            ],
        )
        assert _semantic_role(store, "DescriptorChild") == "descriptor"
        assert _semantic_role(store, "HookBase") == "init-subclass-hook"
    finally:
        store.close()
