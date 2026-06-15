"""Shared PyClass method-name tagging helper (v1.11-#2).

Consolidates the duplicated shape used by four sibling connectors:

* :mod:`knowledge_graph.connectors.py_descriptor_semantics`
  (v1.8-#4 + v1.9-#4 inheritance chasing)
* :mod:`knowledge_graph.connectors.py_set_name_semantics` (v1.9-#2)
* :mod:`knowledge_graph.connectors.py_init_subclass_semantics`
  (v1.10-#4)

Each of those connectors used to walk every ``PyClass`` row, index its
direct ``PyFunction`` children via ``PARENT_OF``, check for a specific
method name, and stamp ``payload['semantic_role']`` — refusing to
overwrite a role set by an earlier connector. The only differences
were the method name string, the role string, and whether bases were
chased (descriptor only).

This module exposes the single helper
:func:`tag_pyclass_by_method`. The four refactored connectors are
now thin wrappers that just call it with their fixed
``(method_name, role, chase_bases)`` triple.

Precedence rule
---------------
A PyClass whose ``semantic_role`` payload entry is already populated
(non-None) is silently skipped. This preserves the
"decorator-wins / descriptor-wins / set-name-hook-wins" precedence
chain documented across the wrapping connectors.

Inheritance scope (``chase_bases=True``)
---------------------------------------
Bases are matched by ``payload['bases']`` strings against PyClass rows
in the **same corpus only**. Bases not present in the corpus
(typically ``object`` or stdlib classes like ``typing.Generic``) are
silently skipped — no external introspection.

Out-of-corpus base contract (v1.14-#4)
--------------------------------------
The base-chase walk explicitly terminates at an out-of-corpus hop: a
base name that does not resolve via ``name_to_id`` is dropped on the
floor (``continue``), the walker does not synthesise a placeholder, and
no role is propagated through the missed hop. Concretely:

* ``class B(ExternalBase): pass`` — never tagged. Chase begins at
  ``B``, finds ``ExternalBase`` unresolved, terminates with no match.
* ``A -> B(A) -> C(External) -> D(C)`` where ``A`` declares the method:
  ``A`` and ``B`` tag from the in-corpus prefix; ``C`` and ``D`` stay
  untagged because the chain breaks at ``C``'s OOC base — the walker
  cannot see anything beyond ``C`` in the corpus, and ``D``'s only
  in-corpus base is ``C`` (itself never tagged).
* ``chase_bases=False`` connectors (set-name-hook) trivially satisfy
  the contract: they never recurse, so an OOC base is irrelevant.

Cycle safety
------------
The walker keeps a ``seen`` set seeded with the starting node id and
extended with every resolved ancestor id. Declared base cycles
(``class A(B)`` / ``class B(A)`` after a refactor mishap) and diamond
inheritance both terminate.

Precedence rule (re-stated)
---------------------------
``payload['semantic_role']`` is single-valued. A row whose role is
already non-None is silently skipped — descriptor (v1.8-#4 +
v1.9-#4) wins over set-name-hook (v1.9-#2) wins over
init-subclass-hook (v1.10-#4 + v1.11-#4) because the connectors run in
that order and this helper never overwrites.
"""

from __future__ import annotations

import json
from typing import Any


def tag_pyclass_by_method(
    store: Any,
    method_name: str,
    role: str,
    *,
    chase_bases: bool = False,
) -> int:
    """Stamp ``semantic_role=role`` onto every PyClass whose direct
    PyFunction children include ``method_name`` (and, when
    ``chase_bases=True``, also onto every PyClass whose in-corpus
    ancestor chain reaches such a class).

    Parameters
    ----------
    store
        A KGWeave store handle exposing ``conn`` (the kuzu connection).
    method_name
        The dunder/method name to look for as a direct child
        ``PyFunction`` of each ``PyClass``.
    role
        The string written into ``payload['semantic_role']`` on
        qualifying rows.
    chase_bases
        When ``True``, also tag classes that inherit the method
        transitively from in-corpus bases. When ``False`` (default),
        only directly-declaring classes qualify.

    Returns
    -------
    int
        Number of PyClass rows written. Idempotent: re-running on a
        tagged store re-writes the same rows and returns the same
        count.
    """
    conn = store.conn

    # Step 1: index every PyFunction's parent PyClass via PARENT_OF.
    # Shape: {pyclass_id: set(method_name, ...)}. Direct children only —
    # no transitive traversal — matches the original closed rules.
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

    # Step 2: walk every PyClass. When chase_bases=True, build parallel
    # indices keyed by corpus for inheritance resolution — name_to_id
    # resolves a base reference back to its PyClass row, bases_index
    # holds declared base names, corpus_of confines resolution to the
    # same corpus as the subclass.
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
        if chase_bases:
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

    def _has_inherited_method(start_nid: str) -> bool:
        """Walk declared bases (recursively, same-corpus only). True if
        any reachable ancestor directly declares ``method_name``.
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
            if methods and method_name in methods:
                return True
            stack.extend(bases_index.get(resolved, []))
        return False

    touched = 0
    for nid, payload_str in rows:
        methods = method_index.get(nid)
        directly = bool(methods and method_name in methods)
        if not directly:
            if not chase_bases or not _has_inherited_method(nid):
                continue
        try:
            payload_obj = json.loads(payload_str)
        except (TypeError, ValueError):
            continue
        inner = payload_obj.get("payload")
        if not isinstance(inner, dict):
            continue
        # Precedence: never overwrite an existing semantic_role set by
        # an earlier connector.
        if inner.get("semantic_role") is not None:
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


__all__ = ["tag_pyclass_by_method"]
