"""``@property`` / ``@functools.cached_property`` semantic-role tagging
for Python descriptor methods (v1.15-#4).

A method decorated with ``@property`` or ``@functools.cached_property``
is a data descriptor bound to its consumer class. This connector tags
every qualifying ``PyFunction`` row with
``payload['semantic_role'] = "property-descriptor"``.

Detection rule
--------------
A ``PyFunction`` qualifies when at least one of its decorators
canonicalises to one of:

* ``property`` (the builtin — usually unaliased)
* ``builtins.property`` (alias-resolved form of ``property``)
* ``functools.cached_property``

The walker emits decorator strings as written in source (v1.6-#3 G1).
We canonicalise each by stripping any call-argument suffix and then
rewriting the leading dotted segment through the per-file alias map
recorded on every ``PyImport`` payload (v1.8-#1).

Consumer-class scope
--------------------
PyClass tagging is deliberately unchanged. The descriptor *is* the
function; the class that holds it is just the owner. Only the
``PyFunction`` row is touched.

Precedence
----------
``semantic_role`` on ``PyFunction`` is single-valued. The pre-existing
``PyDecoratorSemanticsConnector`` already promotes ``@property`` to
role ``"property"``; if it has run first this connector observes
``semantic_role`` set and skips the row, leaving that pre-existing tag
intact (idempotent + non-clobbering).

Idempotence
-----------
Re-running on a tagged store re-sets the same role on the same rows
and returns the same "rows touched" count.
"""

from __future__ import annotations

import json


_TARGET_CANONICALS: frozenset[str] = frozenset(
    {
        "property",
        "builtins.property",
        "functools.cached_property",
    }
)

_ROLE: str = "property-descriptor"


def _canonical_decorator_name(raw: str) -> str:
    """Strip any call-argument suffix and surrounding whitespace.

    Mirrors :func:`py_decorator_semantics._canonical_decorator_name`.
    """
    head, _, _ = raw.partition("(")
    return head.strip()


def _apply_alias_map(name: str, aliases: dict[str, str]) -> str:
    """Rewrite the leading dotted segment of ``name`` through ``aliases``.

    Mirrors :func:`py_decorator_semantics._apply_alias_map`.
    """
    if not name:
        return name
    head, dot, tail = name.partition(".")
    canonical_head = aliases.get(head)
    if canonical_head is None:
        return name
    return f"{canonical_head}.{tail}" if dot else canonical_head


def _matches_property(decorators: list[str], aliases: dict[str, str]) -> bool:
    """True if any decorator canonicalises to a target name."""
    for dec in decorators:
        canonical = _canonical_decorator_name(dec)
        canonical = _apply_alias_map(canonical, aliases)
        if canonical in _TARGET_CANONICALS:
            return True
    return False


class PyPropertyDescriptorConnector:
    """Tag ``@property`` / ``@functools.cached_property`` methods with
    ``semantic_role='property-descriptor'`` on ``PyFunction`` rows.
    """

    name: str = "py-property-descriptor"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        conn = store.conn

        # Step 1: per-origin alias maps from PyImport payloads
        # (mirrors py_decorator_semantics.py Step 1).
        aliases_by_origin: dict[str, dict[str, str]] = {}
        res_imp = conn.execute(
            """
            MATCH (n:Node)
            WHERE n.source = 'py'
              AND n.kind = 'PyImport'
              AND n.payload IS NOT NULL
            RETURN n.origin_id, n.payload
            """,
            {},
        )
        while res_imp.has_next():
            row = res_imp.get_next()
            origin_id, payload_str = row[0], row[1]
            if origin_id is None or payload_str is None:
                continue
            try:
                payload_obj = json.loads(payload_str)
            except (TypeError, ValueError):
                continue
            inner = payload_obj.get("payload")
            if not isinstance(inner, dict):
                continue
            aliases = inner.get("aliases")
            if not isinstance(aliases, dict) or not aliases:
                continue
            bucket = aliases_by_origin.setdefault(origin_id, {})
            for local, canonical in aliases.items():
                if isinstance(local, str) and isinstance(canonical, str):
                    bucket[local] = canonical

        # Step 2: walk PyFunction rows.
        res = conn.execute(
            """
            MATCH (n:Node)
            WHERE n.source = 'py'
              AND n.kind = 'PyFunction'
              AND n.payload IS NOT NULL
            RETURN n.id, n.payload, n.origin_id
            """,
            {},
        )
        rows: list[tuple[str, str, str]] = []
        while res.has_next():
            row = res.get_next()
            rows.append((row[0], row[1], row[2]))

        touched = 0
        for nid, payload_str, origin_id in rows:
            try:
                payload_obj = json.loads(payload_str)
            except (TypeError, ValueError):
                continue
            inner = payload_obj.get("payload")
            if not isinstance(inner, dict):
                continue
            # Precedence: skip rows already carrying a more-specific role.
            if inner.get("semantic_role"):
                continue
            decorators = inner.get("decorators")
            if not isinstance(decorators, list) or not decorators:
                continue
            aliases = aliases_by_origin.get(origin_id, {})
            if not _matches_property([str(d) for d in decorators], aliases):
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


__all__ = ["PyPropertyDescriptorConnector"]
