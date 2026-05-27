"""Direct unit tests for ``tag_pyclass_by_method`` (v1.12-#4).

Extends ``test_py_class_tag.py`` (v1.11-#2) with edge cases the helper
must handle correctly but which the three caller-side connector tests
never exercise:

1. **Precedence under both flags** — pre-set ``semantic_role`` is never
   overwritten by either ``chase_bases=False`` or ``chase_bases=True``.
2. **chase_bases=False isolation** — a subclass that only inherits the
   method does NOT get tagged.
3. **chase_bases=True 4-hop chain** — A → B(A) → C(B) → D(C) all tagged
   when only A declares the method.
4. **chase_bases=True cycle** — A's declared bases include B, B's
   declared bases include A. The helper must terminate cleanly (no
   infinite loop). A short pytest-timeout makes a regression hang
   detectable rather than wedging the whole suite.
5. **chase_bases=True multiple inheritance** — B has bases [A1, A2],
   only A2 declares the method; B gets tagged.

The cycle case requires a static graph state Python's runtime won't
let us produce naturally — we extract a normal hierarchy and then
patch the ``bases`` payload directly to install the back-edge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_graph import cypher, extract, open_store
from knowledge_graph.connectors._py_class_tag import tag_pyclass_by_method


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


def _force_role(store, name: str, role: str) -> None:
    """Stamp ``semantic_role`` directly on the named PyClass payload."""
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyClass'"
        " AND n.name=$name RETURN n.id AS id, n.payload AS p",
        {"name": name},
    )
    assert res.rows, f"PyClass {name!r} not found"
    nid = res.rows[0]["id"]
    payload = json.loads(res.rows[0]["p"])
    inner = payload.setdefault("payload", {})
    inner["semantic_role"] = role
    new_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    store.conn.execute(
        "MATCH (n:Node {id: $id}) SET n.payload = $payload",
        {"id": nid, "payload": new_payload},
    )


def _set_bases(store, name: str, bases: list[str]) -> None:
    """Overwrite ``payload['bases']`` directly on the named PyClass.

    Lets us forge static graph states the Python runtime would refuse
    to produce (e.g. cycles in declared bases).
    """
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyClass'"
        " AND n.name=$name RETURN n.id AS id, n.payload AS p",
        {"name": name},
    )
    assert res.rows, f"PyClass {name!r} not found"
    nid = res.rows[0]["id"]
    payload = json.loads(res.rows[0]["p"])
    inner = payload.setdefault("payload", {})
    inner["bases"] = bases
    new_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    store.conn.execute(
        "MATCH (n:Node {id: $id}) SET n.payload = $payload",
        {"id": nid, "payload": new_payload},
    )


def test_precedence_preset_role_preserved_under_both_flags(tmp_path: Path) -> None:
    """A pre-set ``semantic_role`` must survive a call to the helper
    with ``chase_bases=False`` AND a subsequent call with
    ``chase_bases=True``. The precedence rule is flag-independent.
    """
    fixture = tmp_path / "preset_both.py"
    fixture.write_text(
        '"""Pre-set role survives helper under either flag value."""\n'
        "\n"
        "class A:\n"
        "    def __get__(self, instance, owner=None):\n"
        "        return 1\n"
        "\n"
        "class B(A):\n"
        "    pass\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="cls-tag-direct", paths=[fixture])
        _force_role(store, "A", "dataclass")
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=False)
        assert _semantic_role(store, "A") == "dataclass"
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=True)
        assert _semantic_role(store, "A") == "dataclass"
    finally:
        store.close()


def test_chase_bases_false_skips_inheriting_subclass(tmp_path: Path) -> None:
    """``B(A)`` only inherits ``__get__``; ``chase_bases=False`` must
    not tag it, even though A is tagged.
    """
    fixture = tmp_path / "no_chase.py"
    fixture.write_text(
        '"""Direct-only tagging when chase_bases=False."""\n'
        "\n"
        "class A:\n"
        "    def __get__(self, instance, owner=None):\n"
        "        return 1\n"
        "\n"
        "class B(A):\n"
        "    pass\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="cls-tag-direct", paths=[fixture])
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=False)
        assert _semantic_role(store, "A") == "descriptor"
        assert _semantic_role(store, "B") is None
    finally:
        store.close()


def test_chase_bases_true_four_hop_chain(tmp_path: Path) -> None:
    """``A → B(A) → C(B) → D(C)`` — all four tagged when only A
    declares the method and ``chase_bases=True``.
    """
    fixture = tmp_path / "four_hop.py"
    fixture.write_text(
        '"""Four-hop inheritance chain — chase_bases=True tags all."""\n'
        "\n"
        "class A:\n"
        "    def __get__(self, instance, owner=None):\n"
        "        return 1\n"
        "\n"
        "class B(A):\n"
        "    pass\n"
        "\n"
        "class C(B):\n"
        "    pass\n"
        "\n"
        "class D(C):\n"
        "    pass\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="cls-tag-direct", paths=[fixture])
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=True)
        assert _semantic_role(store, "A") == "descriptor"
        assert _semantic_role(store, "B") == "descriptor"
        assert _semantic_role(store, "C") == "descriptor"
        assert _semantic_role(store, "D") == "descriptor"
    finally:
        store.close()


@pytest.mark.timeout(5)
def test_chase_bases_true_cycle_terminates(tmp_path: Path) -> None:
    """Illegal cycle in declared bases (A's bases include B, B's bases
    include A) must NOT hang the helper. The ``seen`` set guards the
    walk. ``pytest-timeout`` makes a regression fail fast instead of
    looping forever.

    Neither A nor B declares the method here, so neither should be
    tagged — the assertion is termination + correct (no-op) result.
    """
    fixture = tmp_path / "cycle.py"
    fixture.write_text(
        '"""Static graph cycle in declared bases — must terminate."""\n'
        "\n"
        "class A:\n"
        "    pass\n"
        "\n"
        "class B:\n"
        "    pass\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="cls-tag-direct", paths=[fixture])
        # Forge the cycle directly in the payload, post-extraction.
        _set_bases(store, "A", ["B"])
        _set_bases(store, "B", ["A"])
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=True)
        assert _semantic_role(store, "A") is None
        assert _semantic_role(store, "B") is None
    finally:
        store.close()


def test_chase_bases_true_multiple_inheritance(tmp_path: Path) -> None:
    """``B(A1, A2)`` where only A2 declares the method — B must be
    tagged. Walking only the first base would miss this.
    """
    fixture = tmp_path / "multi_inh.py"
    fixture.write_text(
        '"""Multiple inheritance — second base declares the method."""\n'
        "\n"
        "class A1:\n"
        "    pass\n"
        "\n"
        "class A2:\n"
        "    def __get__(self, instance, owner=None):\n"
        "        return 1\n"
        "\n"
        "class B(A1, A2):\n"
        "    pass\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="cls-tag-direct", paths=[fixture])
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=True)
        assert _semantic_role(store, "A1") is None
        assert _semantic_role(store, "A2") == "descriptor"
        assert _semantic_role(store, "B") == "descriptor"
    finally:
        store.close()
