"""Store-backed saved-query registry.

A *saved query* is a named, parameterized analysis that runs natively
against the persisted :class:`~knowledge_graph.store.KGStore` (via
``store.conn``) and returns a typed :class:`QueryResult`. Unlike the
research prototype's ``saved.py`` — which spun up a throwaway temp-dir
store per call — these run directly over the live store the caller already
holds open.

First (and currently only) entry: ``cone_of_influence``.

ANTI-CIRCULARITY (design contract):
    The canonical dict-walk
    :func:`knowledge_graph.builders.sv.semantic.queries.flow.cone_of_influence`
    stays as the *internal build/test oracle*. This saved query reproduces
    the same backward-reachability set **independently** — an iterative
    Cypher frontier over ``store.conn`` — and must NOT call ``flow.py``. A
    test asserts the two agree on the live corpus, which is only meaningful
    because the two paths are independent.

Read-only by construction: every statement issued is a ``MATCH``/``RETURN``.
"""

from __future__ import annotations

import difflib
import json
from typing import Any, Callable

from knowledge_graph.query.results import NodeView, QueryResult
from knowledge_graph.query.runner import _node_dict_to_view

__all__ = ["saved_query", "SavedQueryError", "SAVED_QUERIES"]


class SavedQueryError(KeyError):
    """Raised when ``saved_query`` is asked for an unregistered name.

    Carries a ``difflib`` near-miss suggestion when one exists.
    """

    def __init__(self, name: str, known: list[str]) -> None:
        self.name = name
        self.known = known
        match = difflib.get_close_matches(name, known, n=1, cutoff=0.4)
        self.suggestion = match[0] if match else None
        tail = f" (did you mean {self.suggestion!r}?)" if self.suggestion else ""
        super().__init__(
            f"unknown saved query {name!r}; "
            f"known: {sorted(known)!r}{tail}"
        )


# --------------------------------------------------------------- helpers


def _scalar_rows(conn, cypher: str, params: dict[str, Any]) -> list[Any]:
    """Run ``cypher`` and return the first column of every row."""
    res = conn.execute(cypher, params)
    out: list[Any] = []
    while res.has_next():
        out.append(res.get_next()[0])
    return out


def _resolve_target(conn, target: str) -> str | None:
    """Resolve a signal ``target`` to a node id over the store.

    Mirrors ``connectivity.find_by_name`` semantics natively:

    * exact ``semantic.path`` match wins;
    * otherwise a unique ``.<target>`` path suffix (or bare-leaf) match.

    The promoted ``semantic`` dict lives JSON-encoded in ``Node.payload``;
    we scan the (read-only) ``:Node`` rows and resolve in Python — Kuzu
    cannot index into the JSON string.
    """
    res = conn.execute(
        "MATCH (n:Node) WHERE n.category = 'semantic' "
        "RETURN n.id, n.payload"
    )
    by_path: dict[str, str] = {}
    while res.has_next():
        nid, payload = res.get_next()
        sem = _semantic_of(payload)
        path = sem.get("path")
        if isinstance(path, str) and path:
            by_path[path] = nid

    if target in by_path:
        return by_path[target]
    suffix = "." + target
    candidates = [
        nid for path, nid in by_path.items()
        if path == target or path.endswith(suffix)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _semantic_of(payload: Any) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    sem = decoded.get("semantic") if isinstance(decoded, dict) else None
    return sem if isinstance(sem, dict) else {}


def _hydrate_ids(conn, ids: set[str]) -> list[NodeView]:
    """Hydrate a set of node ids to ``NodeView``s (id-sorted, deterministic)."""
    views: list[NodeView] = []
    for nid in sorted(ids):
        res = conn.execute(
            "MATCH (n:Node) WHERE n.id = $id RETURN n LIMIT 1",
            {"id": nid},
        )
        if res.has_next():
            views.append(_node_dict_to_view(res.get_next()[0]))
    return views


# --------------------------------------------------------- cone_of_influence


def _cone_of_influence(store, **params: Any) -> QueryResult:
    """Backward reachability cone, reproduced over the store.

    Independent re-implementation of ``flow.cone_of_influence``: for each
    node in the frontier, expand its DRIVERS (inbound ``DRIVES``), each
    driver's READS (outbound ``READS``), and inbound ``CONNECTS`` parents;
    iterate to fixpoint. The result set INCLUDES the resolved target.

    ``params`` requires ``target`` — a signal name or ``module.signal``
    path resolvable to a single ``:Node``. An unresolvable target yields
    an empty (but successful) result.
    """
    target = params.get("target")
    if not isinstance(target, str) or not target:
        raise TypeError("cone_of_influence requires a string 'target' param")

    conn = store.conn
    start = _resolve_target(conn, target)
    if start is None:
        return QueryResult(intent_kind="saved", nodes=[])

    seen: set[str] = set()
    frontier: list[str] = [start]
    while frontier:
        nxt: list[str] = []
        for nid in frontier:
            if nid in seen:
                continue
            seen.add(nid)
            drivers = _scalar_rows(
                conn,
                "MATCH (d:Node)-[:DRIVES]->(n:Node) "
                "WHERE n.id = $id RETURN d.id",
                {"id": nid},
            )
            for did in drivers:
                if did not in seen:
                    nxt.append(did)
                for rid in _scalar_rows(
                    conn,
                    "MATCH (d:Node)-[:READS]->(r:Node) "
                    "WHERE d.id = $id RETURN r.id",
                    {"id": did},
                ):
                    if rid not in seen:
                        nxt.append(rid)
            for pid in _scalar_rows(
                conn,
                "MATCH (p:Node)-[:CONNECTS]->(n:Node) "
                "WHERE n.id = $id RETURN p.id",
                {"id": nid},
            ):
                if pid not in seen:
                    nxt.append(pid)
        frontier = nxt

    return QueryResult(intent_kind="saved", nodes=_hydrate_ids(conn, seen))


# ------------------------------------------------------------------ registry

# name -> callable(store, **params) -> QueryResult
SAVED_QUERIES: dict[str, Callable[..., QueryResult]] = {
    "cone_of_influence": _cone_of_influence,
}


def saved_query(store, name: str, **params: Any) -> QueryResult:
    """Run the registered saved query ``name`` against ``store``.

    Unknown ``name`` raises :class:`SavedQueryError` (with a difflib
    suggestion when one is close). Mirrors the ``query()`` / ``cypher()``
    signature style: first positional is the :class:`KGStore`.
    """
    fn = SAVED_QUERIES.get(name)
    if fn is None:
        raise SavedQueryError(name, list(SAVED_QUERIES))
    return fn(store, **params)
