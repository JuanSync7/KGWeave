"""``__init_subclass__`` protocol-hook semantic-role tagging for Python
classes (v1.10-#4).

PEP 487 introduced ``__init_subclass__(cls, **kwargs)`` as a
subclass-creation hook: the interpreter calls it on the parent class
every time a new subclass is created. Any class declaring
``__init_subclass__`` participates in the protocol.

This connector tags every qualifying ``PyClass`` with
``payload['semantic_role'] = "init-subclass-hook"``.

Detection rule (closed)
-----------------------
A ``PyClass`` qualifies iff at least one of its direct ``PyFunction``
children (via ``PARENT_OF``) is named exactly ``__init_subclass__``.
Inheritance is NOT chased — mirrors v1.9-#2's closed rule.

Precedence
----------
``semantic_role`` is a single-valued payload field. Order from
most-specific to least-specific is:

1. ``dataclass`` / ``property`` / ``fixture`` (decorator-driven,
   v1.7-#4 / v1.8-#1) — *explicit*.
2. ``descriptor`` (v1.8-#4) — structural, the ``__get__`` binding
   method.
3. ``set-name-hook`` (v1.9-#2) — structural, the binding-time hook
   (PEP 487 ``__set_name__``).
4. ``init-subclass-hook`` (this connector) — structural, the
   subclass-creation hook (PEP 487 ``__init_subclass__``). Lower
   precedence than descriptor / set-name-hook because those are more
   specific structural shapes.

This connector skips any PyClass whose ``semantic_role`` is already
set, making it commutative with re-runs of any earlier connector.

Idempotence
-----------
Re-running on a tagged store re-sets the same role on the same rows
and returns the same "rows touched" count. Same convention as
:mod:`knowledge_graph.connectors.py_set_name_semantics`.
"""

from __future__ import annotations

import json


_INIT_SUBCLASS_METHOD: str = "__init_subclass__"
_ROLE: str = "init-subclass-hook"


class PyInitSubclassSemanticsConnector:
    """Tag ``__init_subclass__``-hook classes with ``semantic_role='init-subclass-hook'``.

    Reads every ``PyClass`` row in the store. For each, queries
    ``PARENT_OF`` for direct ``PyFunction`` children and checks whether
    any is named ``__init_subclass__``. If yes — and ``semantic_role``
    is not already set by an earlier connector (decorator-wins,
    descriptor-wins, set-name-hook-wins) — writes
    ``payload['semantic_role'] = "init-subclass-hook"`` back into the
    JSON column.

    Returns the number of PyClass rows touched (idempotent re-runs
    return the same count, matching the other connectors' convention).
    """

    name: str = "py-init-subclass-semantics"
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
            if not methods or _INIT_SUBCLASS_METHOD not in methods:
                continue
            try:
                payload_obj = json.loads(payload_str)
            except (TypeError, ValueError):
                continue
            inner = payload_obj.get("payload")
            if not isinstance(inner, dict):
                continue
            # Decorator-wins / descriptor-wins / set-name-hook-wins
            # precedence: never overwrite an existing semantic_role
            # from a prior tagger.
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


__all__ = ["PyInitSubclassSemanticsConnector"]
