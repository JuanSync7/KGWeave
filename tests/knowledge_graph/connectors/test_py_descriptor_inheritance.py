"""PyDescriptorSemanticsConnector inheritance chasing (v1.9-#4).

Extends v1.8-#4: a ``PyClass`` is tagged ``semantic_role='descriptor'``
not only when it directly declares ``__get__`` but also when it
inherits ``__get__`` (transitively) from a base class present in the
same corpus. Bases not in the corpus (e.g. ``object``) are skipped.
Precedence: an existing ``semantic_role`` (dataclass, descriptor from
direct declaration, set-name-hook, etc.) is never overwritten.
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
        corpus="desc-inh",
        paths=[FIXTURE_DIR / fixture],
    )
    run_connectors(store, only=["py-descriptor-semantics"])


def test_subclass_inherits_get_tagged_descriptor(tmp_path: Path) -> None:
    """``B(A)`` with no methods inherits ``__get__`` from ``A`` and is
    tagged ``semantic_role='descriptor'``; ``A`` itself remains tagged
    via direct declaration.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "descriptor_inherited.py")
        assert _semantic_role(store, "A") == "descriptor"
        assert _semantic_role(store, "B") == "descriptor"
    finally:
        store.close()


def test_multi_hop_inheritance_propagates_descriptor_role(tmp_path: Path) -> None:
    """``A`` declares ``__get__``; ``B(A)`` and ``C(B)`` both
    transitively qualify and are tagged.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "descriptor_inherited_multi_hop.py")
        assert _semantic_role(store, "A") == "descriptor"
        assert _semantic_role(store, "B") == "descriptor"
        assert _semantic_role(store, "C") == "descriptor"
    finally:
        store.close()


def test_inheritance_skips_bases_outside_corpus(tmp_path: Path) -> None:
    """Bases not present in the corpus (``object``, ``typing.Generic``)
    must be ignored — they do not promote the subclass to descriptor.
    """
    fixture = tmp_path / "extern_base.py"
    fixture.write_text(
        '"""Subclass of an out-of-corpus base — must NOT be tagged."""\n'
        "\n"
        "class NotDesc(object):\n"
        "    pass\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="desc-inh", paths=[fixture])
        run_connectors(store, only=["py-descriptor-semantics"])
        assert _semantic_role(store, "NotDesc") is None
    finally:
        store.close()


def test_external_descriptor_base_does_not_tag_subclass(tmp_path: Path) -> None:
    """v1.14-#4: ``class B(ExternalDescriptor)`` where the base is not in
    the corpus — chase terminates cleanly; ``B`` stays untagged.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "descriptor_external_base.py")
        assert _semantic_role(store, "B") is None
    finally:
        store.close()


def test_descriptor_chain_breaks_at_ooc_mid_hop(tmp_path: Path) -> None:
    """v1.14-#4: 4-hop chain A -> B(A) -> C(ExternalC) -> D(C) where A
    declares ``__get__``. In-corpus prefix (A, B) tagged; chain breaks at
    OOC ``C`` so neither ``C`` nor ``D`` is tagged.
    """
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _run(store, "descriptor_chain_ooc_mid.py")
        assert _semantic_role(store, "A") == "descriptor"
        assert _semantic_role(store, "B") == "descriptor"
        assert _semantic_role(store, "C") is None
        assert _semantic_role(store, "D") is None
    finally:
        store.close()


def test_inherited_descriptor_precedence_with_set_name(tmp_path: Path) -> None:
    """If both descriptor (via inheritance) and set-name-hook connectors
    would apply, descriptor wins because it runs to the precedence rule
    of leaving an already-set role alone, and we run descriptor first.

    Setup: ``A`` declares ``__get__``; ``B(A)`` declares
    ``__set_name__`` only. After descriptor runs, ``B`` is tagged
    ``"descriptor"`` (inherited). The set-name connector must then NOT
    overwrite it.
    """
    from knowledge_graph.connectors.py_set_name_semantics import (
        PySetNameSemanticsConnector,
    )

    register_connector(PySetNameSemanticsConnector())
    fixture = tmp_path / "desc_inh_with_setname.py"
    fixture.write_text(
        '"""Inherited descriptor + own __set_name__ — descriptor wins."""\n'
        "\n"
        "class A:\n"
        "    def __get__(self, instance, owner=None):\n"
        "        return 1\n"
        "\n"
        "class B(A):\n"
        "    def __set_name__(self, owner, name):\n"
        "        self._name = name\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="desc-inh", paths=[fixture])
        run_connectors(
            store,
            only=["py-descriptor-semantics", "py-set-name-semantics"],
        )
        assert _semantic_role(store, "A") == "descriptor"
        assert _semantic_role(store, "B") == "descriptor"
    finally:
        store.close()
