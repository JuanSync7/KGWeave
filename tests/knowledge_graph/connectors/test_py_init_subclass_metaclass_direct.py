"""Direct unit tests for ``_tag_via_metaclass`` (v1.15-#1).

Pins the v1.14-#2 metaclass-pass helper in
``py_init_subclass_semantics.py`` at its boundary, independent of the
upstream extraction pipeline. Tests insert ``PyClass`` ``:Node`` rows
directly with fabricated payloads so each case exercises exactly the
helper's resolution rules — full-dotted then trailing-segment within
the same corpus, ``semantic_role`` precedence, and out-of-corpus /
missing-role negatives.

Cases:

1. Positive — in-corpus metaclass row carries
   ``semantic_role='init-subclass-hook'`` → consumer gets tagged.
2. Negative out-of-corpus — metaclass name absent from corpus →
   consumer NOT tagged.
3. Negative empty-role — metaclass row present but its
   ``semantic_role`` is missing / ``None`` → consumer NOT tagged.
4. Precedence — consumer already has a ``semantic_role`` (e.g.
   ``descriptor``) → helper leaves it alone.
5. Resolution — full-dotted ``pkg.Meta`` resolves when the corpus
   contains a class actually named ``pkg.Meta``; trailing-segment
   fallback resolves a bare ``Meta``-named class when the consumer
   declares ``metaclass='other.Meta'``.
"""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_graph import cypher, open_store
from knowledge_graph.connectors.py_init_subclass_semantics import (
    _tag_via_metaclass,
)


_ROLE = "init-subclass-hook"


def _insert_pyclass(
    store,
    *,
    nid: str,
    name: str,
    corpus: str,
    metaclass: str | None = None,
    semantic_role: str | None = None,
) -> None:
    """Insert a ``PyClass`` :Node row with a fabricated payload."""
    inner: dict[str, object] = {}
    if metaclass is not None:
        inner["metaclass"] = metaclass
    if semantic_role is not None:
        inner["semantic_role"] = semantic_role
    payload = {"payload": inner}
    payload_str = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    store.conn.execute(
        """
        CREATE (:Node {
            id: $id,
            kind: 'PyClass',
            source: 'py',
            corpus: $corpus,
            name: $name,
            payload: $payload
        })
        """,
        {"id": nid, "name": name, "corpus": corpus, "payload": payload_str},
    )


def _semantic_role(store, nid: str) -> str | None:
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.id = $id RETURN n.payload AS p",
        {"id": nid},
    )
    assert res.rows, f"Node {nid!r} not found"
    payload = json.loads(res.rows[0]["p"])
    return payload.get("payload", {}).get("semantic_role")


def test_positive_in_corpus_metaclass_tags_consumer(tmp_path: Path) -> None:
    """Metaclass row exists in same corpus AND carries the target
    ``semantic_role`` — consumer is tagged and the helper reports the
    write."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _insert_pyclass(
            store,
            nid="meta-1",
            name="Meta",
            corpus="c",
            semantic_role=_ROLE,
        )
        _insert_pyclass(
            store,
            nid="cls-1",
            name="Klass",
            corpus="c",
            metaclass="Meta",
        )
        touched = _tag_via_metaclass(store, _ROLE)
        assert touched == 1
        assert _semantic_role(store, "cls-1") == _ROLE
        # Meta itself was already tagged; helper does not retouch it.
        assert _semantic_role(store, "meta-1") == _ROLE
    finally:
        store.close()


def test_negative_metaclass_not_in_corpus(tmp_path: Path) -> None:
    """No row named ``Meta`` in the corpus — consumer stays untagged."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _insert_pyclass(
            store,
            nid="cls-1",
            name="Klass",
            corpus="c",
            metaclass="Meta",
        )
        touched = _tag_via_metaclass(store, _ROLE)
        assert touched == 0
        assert _semantic_role(store, "cls-1") is None
    finally:
        store.close()


def test_negative_metaclass_role_missing(tmp_path: Path) -> None:
    """Metaclass row exists but has no ``semantic_role`` — consumer
    stays untagged. The helper's role-equality check rejects empty /
    ``None`` roles."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _insert_pyclass(
            store,
            nid="meta-1",
            name="Meta",
            corpus="c",
            # No semantic_role at all.
        )
        _insert_pyclass(
            store,
            nid="cls-1",
            name="Klass",
            corpus="c",
            metaclass="Meta",
        )
        touched = _tag_via_metaclass(store, _ROLE)
        assert touched == 0
        assert _semantic_role(store, "cls-1") is None
    finally:
        store.close()


def test_precedence_preset_role_preserved(tmp_path: Path) -> None:
    """Consumer already carries a more-specific ``semantic_role``
    (``descriptor``); helper must not overwrite it even though the
    metaclass would otherwise qualify."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _insert_pyclass(
            store,
            nid="meta-1",
            name="Meta",
            corpus="c",
            semantic_role=_ROLE,
        )
        _insert_pyclass(
            store,
            nid="cls-1",
            name="Klass",
            corpus="c",
            metaclass="Meta",
            semantic_role="descriptor",
        )
        touched = _tag_via_metaclass(store, _ROLE)
        assert touched == 0
        assert _semantic_role(store, "cls-1") == "descriptor"
    finally:
        store.close()


def test_resolution_full_dotted_match(tmp_path: Path) -> None:
    """When the metaclass payload is a full dotted form (``pkg.Meta``)
    and the corpus contains a row whose ``name`` is literally
    ``pkg.Meta``, the full-dotted candidate resolves first."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _insert_pyclass(
            store,
            nid="meta-1",
            name="pkg.Meta",
            corpus="c",
            semantic_role=_ROLE,
        )
        _insert_pyclass(
            store,
            nid="cls-1",
            name="Klass",
            corpus="c",
            metaclass="pkg.Meta",
        )
        touched = _tag_via_metaclass(store, _ROLE)
        assert touched == 1
        assert _semantic_role(store, "cls-1") == _ROLE
    finally:
        store.close()


def test_resolution_trailing_segment_fallback(tmp_path: Path) -> None:
    """The corpus has no ``other.Meta`` row but does have a class
    named ``Meta``. The helper's trailing-segment fallback (after the
    full-dotted miss) resolves to the bare ``Meta`` row."""
    store = open_store(tmp_path / "kg.kuzu")
    try:
        _insert_pyclass(
            store,
            nid="meta-1",
            name="Meta",
            corpus="c",
            semantic_role=_ROLE,
        )
        _insert_pyclass(
            store,
            nid="cls-1",
            name="Klass",
            corpus="c",
            metaclass="other.Meta",
        )
        touched = _tag_via_metaclass(store, _ROLE)
        assert touched == 1
        assert _semantic_role(store, "cls-1") == _ROLE
    finally:
        store.close()
