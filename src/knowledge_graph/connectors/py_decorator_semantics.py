"""Decorator-aware semantic-role promotion for Python nodes (v1.7-#4).

The Python walker (v1.6-#3 G1) records the source text of every
decorator applied to a ``PyFunction`` / ``PyClass`` under
``payload['decorators']`` -- a list of strings, outer-most first. The
walker is deliberately a pure structural lifter; it never reinterprets
those strings. This connector reads them back at connector time and
promotes three specific decorator names to a ``semantic_role`` tag
inside the same JSON payload.

Promotion rules (closed set):

* ``@dataclass`` or ``@dataclasses.dataclass``  -> ``PyClass.payload.semantic_role = "dataclass"``
* ``@pytest.fixture``                           -> ``PyFunction.payload.semantic_role = "fixture"``
* ``@property``                                 -> ``PyFunction.payload.semantic_role = "property"``

Every other decorator (e.g. ``@functools.cache``, ``@staticmethod``,
``@classmethod``, user-defined wrappers) leaves ``semantic_role``
unset. The connector never deletes or rewrites existing payload keys
-- it only adds ``semantic_role`` and is therefore safe to run on a
store that has already been promoted.

Match rule
----------
The walker emits decorator strings as written in source, including
any call-argument list (``functools.lru_cache(maxsize=8)``,
``pytest.fixture(scope="module")``). We canonicalise each decorator
string to its bare dotted name by stripping at the first ``(`` and
trimming, then match against the closed set:

* ``"property"``                              -> ``"property"``
* ``"dataclass"``, ``"dataclasses.dataclass"`` -> ``"dataclass"``
* ``"pytest.fixture"``                         -> ``"fixture"``

The outer-most decorator wins (i.e. the first element of the list).
If multiple decorators stack, only the outer one is considered for
role promotion; downstream consumers that need every decorator can
still read the full ``payload['decorators']`` list.

Persistence
-----------
Node ``payload`` is a single JSON STRING column on the Node table
(see ``store/schema.py``). The connector reads the column, parses
JSON, inserts ``semantic_role`` into the inner ``payload`` dict, and
writes the JSON back via ``SET n.payload = $payload``. ``MERGE`` on
the existing ``id`` keeps the row identity stable so the operation
is idempotent: a second run sets the same role on the same nodes
and reports the same edge-equivalent count.
"""

from __future__ import annotations

import json


# Closed promotion table. Adding a fourth decorator means: pick its
# canonical bare-dotted-name form, pick a role string, and add a row
# below. Nothing else in this file should change.
_DECORATOR_ROLE: dict[str, tuple[str, str]] = {
    # bare-name              -> (target kind,    semantic_role)
    "property":               ("PyFunction",     "property"),
    "dataclass":              ("PyClass",        "dataclass"),
    "dataclasses.dataclass":  ("PyClass",        "dataclass"),
    "pytest.fixture":         ("PyFunction",     "fixture"),
}


def _canonical_decorator_name(raw: str) -> str:
    """Strip any call-argument suffix and surrounding whitespace.

    Walker emits decorator strings as source text, so
    ``@pytest.fixture(scope="module")`` becomes ``"pytest.fixture(scope=\"module\")"``.
    We only care about the dotted callee, so cut at the first ``(``.
    """
    head, _, _ = raw.partition("(")
    return head.strip()


def _role_for(decorators: list[str], kind: str) -> str | None:
    """Return the semantic role for the outer-most matching decorator.

    Walker order is outer-most first. We scan in that order and return
    the first promotion whose target kind matches the node's kind.
    Mismatched (kind, role) pairs -- e.g. someone applies ``@dataclass``
    to a function -- are skipped, not coerced.
    """
    for dec in decorators:
        canonical = _canonical_decorator_name(dec)
        hit = _DECORATOR_ROLE.get(canonical)
        if hit is None:
            continue
        target_kind, role = hit
        if target_kind == kind:
            return role
    return None


class PyDecoratorSemanticsConnector:
    """Promote known decorator names to ``payload.semantic_role`` tags.

    Reads ``payload['decorators']`` from every PyFunction / PyClass
    node in the store, applies the closed promotion table, and writes
    ``payload['semantic_role']`` back into the JSON column when a
    decorator matches. Idempotent: re-running on a promoted store sets
    the same role on the same nodes.

    Returns the number of nodes whose payload was rewritten with a
    fresh ``semantic_role`` value (including unchanged re-runs, so the
    return is "rows touched", not "rows changed" -- matching the
    other connectors' convention).
    """

    name: str = "py-decorator-semantics"
    requires: list[str] = ["py"]

    _TARGET_KINDS: tuple[str, ...] = ("PyFunction", "PyClass")

    def synthesize(self, store) -> int:
        conn = store.conn

        res = conn.execute(
            """
            MATCH (n:Node)
            WHERE n.source = 'py'
              AND n.kind IN $kinds
              AND n.payload IS NOT NULL
            RETURN n.id, n.kind, n.payload
            """,
            {"kinds": list(self._TARGET_KINDS)},
        )
        rows: list[tuple[str, str, str]] = []
        while res.has_next():
            row = res.get_next()
            rows.append((row[0], row[1], row[2]))

        touched = 0
        for nid, kind, payload_str in rows:
            try:
                payload_obj = json.loads(payload_str)
            except (TypeError, ValueError):
                continue
            inner = payload_obj.get("payload")
            if not isinstance(inner, dict):
                continue
            decorators = inner.get("decorators")
            if not isinstance(decorators, list) or not decorators:
                continue
            role = _role_for([str(d) for d in decorators], kind)
            if role is None:
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


__all__ = ["PyDecoratorSemanticsConnector"]
