"""Descriptor-protocol semantic-role tagging for Python classes (v1.8-#4).

A *descriptor* is any class whose instances control attribute access
through one or more of the dunder methods ``__get__`` / ``__set__`` /
``__delete__``. Per the data model documented in
:pep:`252` / the Python data model reference, the binding method is
``__get__`` — a class is a descriptor as soon as it defines
``__get__``; the companion ``__set__`` and ``__delete__`` upgrade it
to a *data* descriptor but are not required for the basic protocol.
This connector tags every qualifying ``PyClass`` with
``payload['semantic_role'] = "descriptor"``.

Detection rule (closed)
-----------------------
A ``PyClass`` qualifies iff at least one of its direct ``PyFunction``
children (via ``PARENT_OF``) is named exactly ``__get__``. Inheritance
is NOT chased: a subclass that inherits ``__get__`` from a parent
without defining it locally is not tagged. (Cross-class resolution is
queued for v1.9 alongside cross-file scope resolution.)

Precedence vs PyDecoratorSemanticsConnector
-------------------------------------------
``semantic_role`` is a single-valued payload field. v1.7-#4 / v1.8-#1
already promote ``@dataclass`` to ``semantic_role='dataclass'`` on
PyClass. A class can in principle be both a ``@dataclass`` and a
descriptor (it defines ``__get__``). We pick **decorator-wins** as the
precedence policy:

* The decorator is *explicit* — the user typed it. Descriptor
  detection is *structural* — inferred from method shape. Explicit
  beats inferred.
* The decorator connector is documented as running first; this
  connector skips any class whose ``semantic_role`` is already set,
  making the operation safely commutative with re-runs of either
  connector.

Idempotence
-----------
Re-running the connector on a tagged store re-sets the same role on
the same rows and returns the same "rows touched" count. Mirrors the
convention in :mod:`knowledge_graph.connectors.py_decorator_semantics`.
"""

from __future__ import annotations

import json


_DESCRIPTOR_BINDING_METHOD: str = "__get__"
_ROLE: str = "descriptor"


class PyDescriptorSemanticsConnector:
    """Tag descriptor-protocol classes with ``semantic_role='descriptor'``.

    Reads every ``PyClass`` row in the store. For each, queries
    ``PARENT_OF`` for direct ``PyFunction`` children and checks whether
    any is named ``__get__``. If yes — and ``semantic_role`` is not
    already set by an earlier connector — writes
    ``payload['semantic_role'] = "descriptor"`` back into the JSON
    column.

    Returns the number of PyClass rows touched (idempotent re-runs
    return the same count, matching the other connectors' convention).
    """

    name: str = "py-descriptor-semantics"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        conn = store.conn

        # Step 1: index every PyFunction's parent PyClass via PARENT_OF.
        # Shape: {pyclass_id: set(method_name, ...)}. Only direct
        # children — no transitive traversal — matches the detection
        # rule (no inheritance chasing).
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
            if not methods or _DESCRIPTOR_BINDING_METHOD not in methods:
                continue
            try:
                payload_obj = json.loads(payload_str)
            except (TypeError, ValueError):
                continue
            inner = payload_obj.get("payload")
            if not isinstance(inner, dict):
                continue
            # Decorator-wins precedence: never overwrite an existing
            # semantic_role set by PyDecoratorSemanticsConnector (or any
            # other prior tagger).
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


__all__ = ["PyDescriptorSemanticsConnector"]
