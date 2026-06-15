"""``__init_subclass__`` protocol-hook semantic-role tagging for Python
classes (v1.10-#4, extended v1.14-#2).

PEP 487 introduced ``__init_subclass__(cls, **kwargs)`` as a
subclass-creation hook: the interpreter calls it on the parent class
every time a new subclass is created. Any class declaring
``__init_subclass__`` participates in the protocol — and so does any
class whose **metaclass** declares it (because instantiating the class
goes through the metaclass's ``__init_subclass__`` machinery).

This connector tags every qualifying ``PyClass`` with
``payload['semantic_role'] = "init-subclass-hook"``.

Detection rule
--------------
A ``PyClass`` qualifies when any of:

1. At least one of its direct ``PyFunction`` children (via
   ``PARENT_OF``) is named exactly ``__init_subclass__``, OR
2. (v1.11-#4 inheritance chasing) any of its in-corpus ancestors
   along the declared ``bases`` chain qualifies under rule 1, OR
3. (v1.14-#2 metaclass pass) its declared ``metaclass=M`` resolves to
   an in-corpus ``PyClass`` that qualifies under rule 1 or 2.

Out-of-corpus bases / metaclasses (e.g. ``object``, ``type``, stdlib)
are silently skipped — no external introspection.

Precedence
----------
``semantic_role`` is a single-valued payload field. Order from
most-specific to least-specific:

1. ``dataclass`` / ``property`` / ``fixture`` (decorator-driven,
   v1.7-#4 / v1.8-#1) — *explicit*.
2. ``descriptor`` (v1.8-#4) — structural ``__get__`` binding method.
3. ``set-name-hook`` (v1.9-#2) — structural ``__set_name__`` hook.
4. ``init-subclass-hook`` (this connector) — structural
   ``__init_subclass__`` hook. Lower precedence than descriptor /
   set-name-hook because those are more specific structural shapes.

The base pass uses the shared helper which enforces precedence by
skipping any class whose ``semantic_role`` is already populated. The
metaclass pass below mirrors that rule.

Idempotence
-----------
Re-running on a tagged store re-sets the same role on the same rows
and returns the same "rows touched" count.
"""

from __future__ import annotations

import json
from typing import Any

from knowledge_graph.connectors._py_class_tag import tag_pyclass_by_method


_INIT_SUBCLASS_METHOD: str = "__init_subclass__"
_ROLE: str = "init-subclass-hook"


class PyInitSubclassSemanticsConnector:
    """Tag ``__init_subclass__``-hook classes with ``semantic_role='init-subclass-hook'``."""

    name: str = "py-init-subclass-semantics"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        # Pass 1 (v1.10-#4 + v1.11-#4): direct declaration + base chain.
        touched = tag_pyclass_by_method(
            store, _INIT_SUBCLASS_METHOD, _ROLE, chase_bases=True
        )
        # Pass 2 (v1.14-#2): metaclass-driven tagging. After pass 1,
        # any in-corpus metaclass that qualifies has semantic_role set
        # to "init-subclass-hook"; we propagate that tag to classes
        # declaring ``metaclass=M``.
        touched += _tag_via_metaclass(store, _ROLE)
        return touched


def _tag_via_metaclass(store: Any, role: str) -> int:
    """Second-pass tagger: for each PyClass with a ``metaclass`` payload
    string, resolve the metaclass name within the same corpus; if the
    resolved metaclass row's ``semantic_role`` equals ``role`` and the
    current class has no role yet, stamp ``role`` on the current class.

    Returns the number of PyClass rows written.
    """
    conn = store.conn

    # Build (corpus, name) -> (id, payload_str) index across all
    # PyClass rows in the store.
    name_to_row: dict[tuple[str, str], tuple[str, str]] = {}
    res = conn.execute(
        """
        MATCH (n:Node)
        WHERE n.source = 'py'
          AND n.kind = 'PyClass'
          AND n.payload IS NOT NULL
        RETURN n.id, n.payload, n.name, n.corpus
        """,
        {},
    )
    all_rows: list[tuple[str, str, str | None, str | None]] = []
    while res.has_next():
        row = res.get_next()
        nid, payload_str, cname, corpus = row[0], row[1], row[2], row[3]
        all_rows.append((nid, payload_str, cname, corpus))
        if cname and corpus is not None:
            name_to_row[(corpus, cname)] = (nid, payload_str)

    touched = 0
    for nid, payload_str, _cname, corpus in all_rows:
        try:
            payload_obj = json.loads(payload_str)
        except (TypeError, ValueError):
            continue
        inner = payload_obj.get("payload")
        if not isinstance(inner, dict):
            continue
        # Precedence: never overwrite an existing role.
        if inner.get("semantic_role") is not None:
            continue
        meta = inner.get("metaclass")
        if not isinstance(meta, str) or not meta or corpus is None:
            continue
        # Resolve metaclass within same corpus; accept both the full
        # dotted form and the trailing segment (mirrors base-chase
        # resolution in _py_class_tag).
        candidates = [meta]
        if "." in meta:
            candidates.append(meta.rsplit(".", 1)[-1])
        meta_row: tuple[str, str] | None = None
        for cand in candidates:
            hit = name_to_row.get((corpus, cand))
            if hit is not None:
                meta_row = hit
                break
        if meta_row is None:
            continue  # metaclass not in corpus — opaque
        try:
            meta_payload_obj = json.loads(meta_row[1])
        except (TypeError, ValueError):
            continue
        meta_inner = meta_payload_obj.get("payload")
        if not isinstance(meta_inner, dict):
            continue
        if meta_inner.get("semantic_role") != role:
            continue
        inner["semantic_role"] = role
        new_payload = json.dumps(
            payload_obj, ensure_ascii=False, sort_keys=True, default=str
        )
        conn.execute(
            "MATCH (n:Node {id: $id}) SET n.payload = $payload",
            {"id": nid, "payload": new_payload},
        )
        touched += 1
    return touched


__all__ = ["PyInitSubclassSemanticsConnector"]
