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
A ``PyClass`` qualifies iff either:

* at least one of its direct ``PyFunction`` children (via
  ``PARENT_OF``) is named exactly ``__get__``; **or**
* (v1.9-#4) any class reachable by chasing ``payload['bases']``
  recursively — restricted to PyClass rows in the same corpus and
  matched by ``name`` — directly declares ``__get__``.

Bases not present in the corpus (typically ``object`` or stdlib
classes like ``typing.Generic``) are silently skipped — there is no
attempt to introspect external code.

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
        # Build parallel indices keyed by corpus for inheritance chasing —
        # name_to_id resolves a base reference back to its PyClass row,
        # bases_index holds declared base names, corpus_of confines
        # resolution to the same corpus as the subclass (v1.9-#4 scope).
        rows: list[tuple[str, str]] = []
        name_to_id: dict[tuple[str, str], str] = {}
        bases_index: dict[str, list[str]] = {}
        corpus_of: dict[str, str] = {}
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
        while res.has_next():
            row = res.get_next()
            nid, payload_str, cname, corpus = row[0], row[1], row[2], row[3]
            rows.append((nid, payload_str))
            if cname:
                name_to_id[(corpus, cname)] = nid
            corpus_of[nid] = corpus
            try:
                payload_obj = json.loads(payload_str)
            except (TypeError, ValueError):
                continue
            inner = payload_obj.get("payload")
            if isinstance(inner, dict):
                bs = inner.get("bases")
                if isinstance(bs, list):
                    bases_index[nid] = [b for b in bs if isinstance(b, str)]

        def _has_inherited_get(start_nid: str) -> bool:
            """Walk declared bases (recursively, same-corpus only). True
            if any reachable ancestor directly declares ``__get__``.
            """
            corpus = corpus_of.get(start_nid)
            if corpus is None:
                return False
            seen: set[str] = {start_nid}
            stack: list[str] = list(bases_index.get(start_nid, []))
            while stack:
                base_name = stack.pop()
                # Match the trailing segment too so ``mod.A`` and bare
                # ``A`` both resolve when ``A`` lives in the corpus.
                candidates = [base_name]
                if "." in base_name:
                    candidates.append(base_name.rsplit(".", 1)[-1])
                resolved: str | None = None
                for cand in candidates:
                    hit = name_to_id.get((corpus, cand))
                    if hit is not None and hit not in seen:
                        resolved = hit
                        break
                if resolved is None:
                    continue  # base not in corpus — skip
                seen.add(resolved)
                methods = method_index.get(resolved)
                if methods and _DESCRIPTOR_BINDING_METHOD in methods:
                    return True
                stack.extend(bases_index.get(resolved, []))
            return False

        touched = 0
        for nid, payload_str in rows:
            methods = method_index.get(nid)
            directly = methods and _DESCRIPTOR_BINDING_METHOD in methods
            if not directly and not _has_inherited_get(nid):
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
