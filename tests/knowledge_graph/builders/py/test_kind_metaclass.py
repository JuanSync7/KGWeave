"""v1.8-#4 G1/G2: metaclass payload on PyClass.

Walker must record the dotted name of the ``metaclass=...`` keyword
argument on the ``PyClass`` payload under ``payload['metaclass']``.
Classes without a metaclass kwarg must report ``None`` (key absent OR
present-with-None — both accepted; we test via ``.get``).
"""
from __future__ import annotations

import json
from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


def _payload_metaclass(payload: dict) -> str | None:
    return payload.get("metaclass")


def test_walker_records_metaclass_basic() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python((FIXTURE_DIR / "metaclass_basic.py").read_bytes())
    by_name = {n.name: n for n in nodes if n.kind == "PyClass"}
    assert _payload_metaclass(by_name["Foo"].payload) == "Meta"
    # ``Meta(type)`` — ``type`` is a positional base, NOT a metaclass kwarg.
    assert _payload_metaclass(by_name["Meta"].payload) is None


def test_walker_records_metaclass_with_positional_bases() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(
        (FIXTURE_DIR / "metaclass_with_bases.py").read_bytes()
    )
    by_name = {n.name: n for n in nodes if n.kind == "PyClass"}
    assert _payload_metaclass(by_name["Foo"].payload) == "Meta"
    assert _payload_metaclass(by_name["Base"].payload) is None
    assert _payload_metaclass(by_name["Meta"].payload) is None


def test_walker_no_metaclass_leaves_field_unset() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python((FIXTURE_DIR / "no_metaclass.py").read_bytes())
    by_name = {n.name: n for n in nodes if n.kind == "PyClass"}
    assert _payload_metaclass(by_name["Plain"].payload) is None
    assert _payload_metaclass(by_name["Bare"].payload) is None
    assert _payload_metaclass(by_name["Base"].payload) is None


def test_writer_roundtrips_metaclass_payload(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(
            store,
            source="py",
            corpus="mc",
            paths=[FIXTURE_DIR / "metaclass_with_bases.py"],
        )
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyClass'"
            " AND n.name='Foo' RETURN n.payload AS p",
        )
        payload = json.loads(res.rows[0]["p"])
        assert payload["payload"]["metaclass"] == "Meta"
    finally:
        store.close()
