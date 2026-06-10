"""Saved-query library — a deliberately tiny registry of named graph walks.

A *saved query* is a parameterised, named graph walk that callers invoke by
name through ``saved_query(graph, name, **params)``. It exists to re-home the
ONE genuine win the old dict surface had over inline Cypher — the cone of
influence — without dragging the whole DSL "tool menu" along with it.

PROMOTION BAR (the guard against rebuilding the dict's tool menu):

    A graph walk earns a place in this registry ONLY if it is BOTH

      1. RECURRING — callers ask for it repeatedly, AND
      2. NOT CLEANLY EXPRESSIBLE as inline Cypher.

    Anything that *is* cleanly expressible inline is a CARD RECIPE (S3) — a
    documented Cypher snippet callers paste and run via ``cypher_query`` — and
    NEVER a saved query or a tool. The cone of influence qualifies because it
    is an alternating, transitive backward walk (drivers → their reads →
    connect-parents, to a fixpoint) that kuzu cannot express as a single inline
    pattern. If you are tempted to add a query here that *could* be one Cypher
    MATCH, stop: write a card recipe instead. Keeping this menu tiny is the
    point of the slice.

ANTI-CIRCULARITY (load-bearing):

    The Python ``cone_of_influence`` in ``flow.py`` is the INDEPENDENT TRUTH
    oracle the equivalence test checks against. This module reproduces the cone
    by an INDEPENDENT route — parameterised kuzu/Cypher queries over the loaded
    projection — and MUST NOT import, call, or delegate to ``flow.py``'s
    ``cone_of_influence`` / ``neighbors`` / ``find_drivers``. Two independent
    implementations that agree is the whole value of the eval; wrapping the
    Python walk would make the equivalence test vacuous.

CONE SEMANTICS (reproduced from flow.py, by an independent Cypher route):

    Backward reachability BFS. ``seen`` starts empty; the frontier starts at
    the target node (matched by ``semantic.path`` OR ``semantic.name``). Each
    iteration, for every not-yet-seen frontier node ``n``:

      * DRIVERS: every ``D`` with ``(D)-[:drives]->(n)`` is added; AND for each
        such ``D``, every ``R`` with ``(D)-[:reads]->(R)`` is added.
      * CONNECT-PARENTS: every ``P`` with ``(P)-[:connects]->(n)`` is added.

    Repeat to fixpoint. The RESULT (``seen``) INCLUDES the target itself, then
    is PROJECTED to the set of ``semantic.path`` values.

LEAK SAFETY:

    The kuzu projection is loaded ONCE per ``saved_query`` call via
    ``_kuzu_load`` (which returns ``(conn, tmpdir)``). The frontier expansion
    runs as parameterised queries against that single ``conn``; we do NOT
    reload per iteration. The temp dir is removed in a ``finally`` via
    ``shutil.rmtree(tmpdir, ignore_errors=True)`` — no leaked ``kg_kuzu_*``.

NO ``import re`` / ``from re`` in this module.
"""

from __future__ import annotations

import difflib
import shutil
from typing import Any, Callable

from .cypher_query import CypherResult

__all__ = ["saved_query", "SavedQueryError"]


class SavedQueryError(Exception):
    """Raised by ``saved_query`` for an unknown registered query name.

    This is a TYPED error (never a bare ``KeyError``) so callers can catch a
    specific exception and surface the available menu plus a near-miss
    suggestion.

    Attributes:
        name:       The unknown query name the caller asked for.
        available:  The sorted list of registered query names.
        suggestion: The nearest registered name (difflib), or ``None``.
    """

    def __init__(
        self,
        name: str,
        available: list[str],
        suggestion: str | None = None,
    ) -> None:
        self.name = name
        self.available = available
        self.suggestion = suggestion
        msg = (
            f"unknown saved query {name!r}; available: {available}"
            + (f" (did you mean {suggestion!r}?)" if suggestion else "")
        )
        super().__init__(msg)


# ---------------------------------------------------------------------------
# cone_of_influence — independent Cypher reproduction of flow.py's walk
# ---------------------------------------------------------------------------


def _cone_of_influence(graph: dict[str, Any], target: str) -> CypherResult:
    """Backward-reachability cone for *target*, computed via kuzu queries.

    Loads the projection once, expands the frontier as parameterised Cypher
    against the single connection to a fixpoint, then projects ``seen`` to
    distinct ``semantic.path`` values. Returns a single-column ``CypherResult``
    (``columns=["path"]``).

    Independent of flow.py — accumulates ids in Python across iterations but
    every expansion step is a kuzu query, not a call into the Python walk.
    """
    from ._kuzu_load import _kuzu_load  # local import to keep kuzu lazy

    conn, tmpdir = _kuzu_load(graph)
    try:
        # Locate the target node id by path OR name (same lookup S1 uses).
        start = _resolve_target_id(conn, target)
        if start is None:
            return CypherResult(columns=["path"], rows=[])

        seen: set[str] = set()
        frontier: list[str] = [start]
        while frontier:
            nxt: set[str] = set()
            # Drop already-seen ids; mark the rest as seen for this round.
            batch = [nid for nid in frontier if nid not in seen]
            seen.update(batch)
            if not batch:
                break

            # DRIVERS of the batch: (D)-[:drives]->(n)
            drivers = _ids(
                conn.execute(
                    "MATCH (d:N)-[:drives]->(n:N) WHERE n.id IN $batch "
                    "RETURN DISTINCT d.id",
                    {"batch": batch},
                )
            )
            nxt.update(d for d in drivers if d not in seen)

            # For each such driver D: (D)-[:reads]->(R)
            if drivers:
                reads = _ids(
                    conn.execute(
                        "MATCH (d:N)-[:reads]->(r:N) WHERE d.id IN $drivers "
                        "RETURN DISTINCT r.id",
                        {"drivers": list(drivers)},
                    )
                )
                nxt.update(r for r in reads if r not in seen)

            # CONNECT-PARENTS of the batch: (P)-[:connects]->(n)
            parents = _ids(
                conn.execute(
                    "MATCH (p:N)-[:connects]->(n:N) WHERE n.id IN $batch "
                    "RETURN DISTINCT p.id",
                    {"batch": batch},
                )
            )
            nxt.update(p for p in parents if p not in seen)

            frontier = list(nxt)

        # Project seen ids to distinct semantic.path values.
        paths = _ids(
            conn.execute(
                "MATCH (n:N) WHERE n.id IN $seen AND n.path IS NOT NULL "
                "RETURN n.path",
                {"seen": list(seen)},
            )
        )
        rows = [{"path": p} for p in sorted(set(paths))]
        return CypherResult(columns=["path"], rows=rows)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _resolve_target_id(conn: Any, target: str) -> str | None:
    """Return the id of the node whose path OR name == *target*, else None.

    Prefers a path match; falls back to a name match. Uses parameterised
    queries against the loaded connection.
    """
    res = conn.execute(
        "MATCH (n:N) WHERE n.path = $t RETURN n.id", {"t": target}
    )
    ids = _ids(res)
    if ids:
        return ids[0]
    res = conn.execute(
        "MATCH (n:N) WHERE n.name = $t RETURN n.id", {"t": target}
    )
    ids = _ids(res)
    return ids[0] if ids else None


def _ids(res: Any) -> list[str]:
    """Drain a single-column kuzu QueryResult into a list of its scalar cells."""
    out: list[str] = []
    while res.has_next():
        row = res.get_next()
        if row and row[0] is not None:
            out.append(row[0])
    return out


# ---------------------------------------------------------------------------
# Registry + dispatch
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Callable[..., CypherResult]] = {
    "cone_of_influence": _cone_of_influence,
}


def saved_query(graph: dict[str, Any], name: str, **params: Any) -> CypherResult:
    """Run the registered saved query *name* over *graph*.

    Args:
        graph:  The in-memory KG dict produced by ``build_kg``.
        name:   The registered query name (e.g. ``"cone_of_influence"``).
        params: Query-specific keyword parameters (e.g. ``target="fifo.count"``).

    Returns:
        A ``CypherResult`` — the settled result type, so callers get
        ``.scalars()`` and ``.rows`` exactly as from ``cypher_query``.

    Raises:
        SavedQueryError: if *name* is not a registered query (a TYPED error,
            never a bare ``KeyError``); it carries the available names and a
            difflib near-miss suggestion.
    """
    fn = _REGISTRY.get(name)
    if fn is None:
        available = sorted(_REGISTRY)
        matches = difflib.get_close_matches(name, available, n=1, cutoff=0.4)
        suggestion = matches[0] if matches else None
        raise SavedQueryError(name, available, suggestion)
    return fn(graph, **params)
