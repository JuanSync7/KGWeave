"""``__set_name__`` protocol-hook semantic-role tagging for Python
classes (v1.9-#2).

PEP 487 introduced ``__set_name__(owner, name)`` as a binding-time
hook: the interpreter calls it on every class attribute that defines
the method, immediately after the owning class is created. The hook is
commonly paired with descriptors but stands on its own — any class
declaring ``__set_name__`` participates in the protocol.

This connector tags every qualifying ``PyClass`` with
``payload['semantic_role'] = "set-name-hook"``.

Detection rule (closed)
-----------------------
A ``PyClass`` qualifies iff at least one of its direct ``PyFunction``
children (via ``PARENT_OF``) is named exactly ``__set_name__``.
Inheritance is NOT chased — mirrors v1.8-#4's closed rule.

Precedence
----------
``semantic_role`` is a single-valued payload field. Order from
most-specific to least-specific is:

1. ``dataclass`` / ``property`` / ``fixture`` (decorator-driven,
   v1.7-#4 / v1.8-#1) — *explicit*.
2. ``descriptor`` (v1.8-#4) — structural, the ``__get__`` binding
   method.
3. ``set-name-hook`` (this connector) — structural, the binding-time
   hook. Descriptor wins because ``__set_name__`` commonly accompanies
   ``__get__`` and the descriptor role is the more specific shape.

This connector skips any PyClass whose ``semantic_role`` is already
set, making it commutative with re-runs of either prior connector.

Idempotence
-----------
Re-running on a tagged store re-sets the same role on the same rows
and returns the same "rows touched" count. Same convention as
:mod:`knowledge_graph.connectors.py_descriptor_semantics`.
"""

from __future__ import annotations

import json


_SET_NAME_METHOD: str = "__set_name__"
_ROLE: str = "set-name-hook"


class PySetNameSemanticsConnector:
    """Tag ``__set_name__``-hook classes with ``semantic_role='set-name-hook'``.

    Reads every ``PyClass`` row in the store. For each, queries
    ``PARENT_OF`` for direct ``PyFunction`` children and checks whether
    any is named ``__set_name__``. If yes — and ``semantic_role`` is
    not already set by an earlier connector (decorator-wins,
    descriptor-wins) — writes
    ``payload['semantic_role'] = "set-name-hook"`` back into the JSON
    column.

    Returns the number of PyClass rows touched (idempotent re-runs
    return the same count, matching the other connectors' convention).
    """

    name: str = "py-set-name-semantics"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        conn = store.conn

        # Step 1: index every PyFunction's parent PyClass via PARENT_OF.
        # Shape: {pyclass_id: set(method_name, ...)}. Direct children
        # only — no transitive traversal — matches the closed rule.
        method_index: dict[str, set[str]] = {}
        res_methods = conn.execute(
            """
            MATCH (c:Node)-[:PARENT_OF]->(f:Node)
            WHERE c.source = 'py' AND c.kind = 'PyClass'
              AND f.source = 'py' AND f.kind = 'PyFunction'
              AND f.name IS NOT NULL
            RETURN c.id, f.name
            """,
            {},
        )
        while res_methods.has_next():
            cid, mname = res_methods.get_next()
            if cid is None or mname is None:
                continue
            method_index.setdefault(cid, set()).add(mname)

        # Step 2: walk every PyClass and decide whether to tag it.
        res = conn.execute(
            """
            MATCH (n:Node)
            WHERE n.source = 'py'
              AND n.kind = 'PyClass'
              AND n.payload IS NOT NULL
            RETURN n.id, n.payload
            """,
            {},
        )
        rows: list[tuple[str, str]] = []
        while res.has_next():
            row = res.get_next()
            rows.append((row[0], row[1]))

        touched = 0
        for nid, payload_str in rows:
            methods = method_index.get(nid)
            if not methods or _SET_NAME_METHOD not in methods:
                continue
            try:
                payload_obj = json.loads(payload_str)
            except (TypeError, ValueError):
                continue
            inner = payload_obj.get("payload")
            if not isinstance(inner, dict):
                continue
            # Decorator-wins / descriptor-wins precedence: never
            # overwrite an existing semantic_role from a prior tagger.
            if inner.get("semantic_role") is not None:
                continue
            inner["semantic_role"] = _ROLE
            new_payload = json.dumps(
                payload_obj, ensure_ascii=False, sort_keys=True, default=str
            )
            conn.execute(
                "MATCH (n:Node {id: $id}) SET n.payload = $payload",
                {"id": nid, "payload": new_payload},
            )
            touched += 1
        return touched


__all__ = ["PySetNameSemanticsConnector"]
