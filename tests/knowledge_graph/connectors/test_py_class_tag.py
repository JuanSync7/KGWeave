"""Helper-direct unit tests for ``tag_pyclass_by_method`` (v1.11-#2).

The helper consolidates the duplicated PyClass→PyFunction method-name
tagging shape used by v1.8-#4 (descriptor), v1.9-#2 (set-name-hook),
v1.9-#4 (inherited descriptor), and v1.10-#4 (init-subclass-hook).

Exercises three contracts:

1. Precedence: a pre-set ``semantic_role`` is never overwritten,
   regardless of the ``chase_bases`` flag.
2. ``chase_bases=False``: a subclass that only INHERITS the named
   method (does not directly declare it) is NOT tagged.
3. ``chase_bases=True``: that same subclass IS tagged via in-corpus
   ancestor walking — mirrors the v1.9-#4 inherited-descriptor pattern.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    """Set ``semantic_role`` directly so we can test precedence."""
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


def test_precedence_pre_set_role_never_overwritten(tmp_path: Path) -> None:
    """A PyClass whose ``semantic_role`` is already populated must be
    skipped by the helper under either ``chase_bases`` value.
    """
    fixture = tmp_path / "preset.py"
    fixture.write_text(
        '"""Two descriptor classes; one has a pre-set role."""\n'
        "\n"
        "class A:\n"
        "    def __get__(self, instance, owner=None):\n"
        "        return 1\n"
        "\n"
        "class B:\n"
        "    def __get__(self, instance, owner=None):\n"
        "        return 2\n"
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="cls-tag", paths=[fixture])
        _force_role(store, "A", "dataclass")
        # chase_bases=False
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=False)
        assert _semantic_role(store, "A") == "dataclass"  # preserved
        assert _semantic_role(store, "B") == "descriptor"
        # Re-run with chase_bases=True — still must not overwrite A.
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=True)
        assert _semantic_role(store, "A") == "dataclass"
    finally:
        store.close()


def test_chase_bases_false_does_not_tag_inheriting_subclass(tmp_path: Path) -> None:
    """``B(A)`` that only inherits the method must NOT be tagged when
    ``chase_bases=False`` (mirrors v1.9-#2 / v1.10-#4 closed rule).
    """
    fixture = tmp_path / "inh_no_chase.py"
    fixture.write_text(
        '"""Subclass inherits __get__ — should NOT be tagged when chase_bases=False."""\n'
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
        extract(store, source="py", corpus="cls-tag", paths=[fixture])
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=False)
        assert _semantic_role(store, "A") == "descriptor"
        assert _semantic_role(store, "B") is None
    finally:
        store.close()


def test_chase_bases_true_tags_inheriting_subclass(tmp_path: Path) -> None:
    """``B(A)`` and ``C(B)`` both transitively qualify under
    ``chase_bases=True`` via in-corpus ancestor walking (v1.9-#4
    pattern).
    """
    fixture = tmp_path / "inh_chase.py"
    fixture.write_text(
        '"""Multi-hop inheritance — chase_bases=True tags all three."""\n'
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
    )
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="cls-tag", paths=[fixture])
        tag_pyclass_by_method(store, "__get__", "descriptor", chase_bases=True)
        assert _semantic_role(store, "A") == "descriptor"
        assert _semantic_role(store, "B") == "descriptor"
        assert _semantic_role(store, "C") == "descriptor"
    finally:
        store.close()
