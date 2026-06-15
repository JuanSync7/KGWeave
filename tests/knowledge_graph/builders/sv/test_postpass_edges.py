"""Partials-wave post-passes: ``of_type`` + ``checks`` edges.

The two global post-passes (:func:`resolve_of_type`,
:func:`resolve_assertion_checks`) run as build phase-4 and emit
``of_type`` (signal → user-defined-type node) and ``checks``
(assertion → checked-signal) edges into the shared graph dict. These
tests assert (a) the dict-level post-passes append the expected edges
and (b) the edges survive the writer into the Kuzu store as ``OF_TYPE``
/ ``CHECKS`` rel tables and are reachable by Cypher.

Fixture: the shared SV corpus already exercises both constructs —
``fifo.sv`` declares ``output fifo_status_e status`` (a port typed by a
package typedef → ``of_type``) and ``fifo_asserts.sv`` carries concurrent
assertions referencing ``push`` / ``full`` (→ ``checks``).
"""

from __future__ import annotations

from typing import Any


# --------------------------------------------------------------- dict-level


def test_resolve_of_type_appends_edges(sv_corpus_graph: dict[str, Any]) -> None:
    """``of_type`` edges land on the lifted graph dict (build phase-4)."""
    of_type = [e for e in sv_corpus_graph["edges"] if e["type"] == "of_type"]
    assert of_type, "expected at least one of_type edge (port typed by typedef)"


def test_resolve_assertion_checks_appends_edges(
    sv_corpus_graph: dict[str, Any],
) -> None:
    """``checks`` edges land on the lifted graph dict (build phase-4)."""
    checks = [e for e in sv_corpus_graph["edges"] if e["type"] == "checks"]
    assert checks, "expected at least one checks edge (assertion → signal)"
    # the checks edge carries the signal name it resolved through
    assert any("name" in (e.get("payload") or {}) for e in checks)


# --------------------------------------------------------------- store-level


def _count_rel(store, rel: str) -> int:
    res = store.conn.execute(f"MATCH ()-[r:{rel}]->() RETURN count(r)")
    return res.get_next()[0]


def test_of_type_rel_persisted(sv_corpus_store) -> None:
    """``OF_TYPE`` rows persist and match the dict edge count."""
    store, graph, _origins, _stats = sv_corpus_store
    dict_count = sum(1 for e in graph["edges"] if e["type"] == "of_type")
    assert dict_count > 0
    assert _count_rel(store, "OF_TYPE") == dict_count


def test_checks_rel_persisted(sv_corpus_store) -> None:
    """``CHECKS`` rows persist and match the dict edge count."""
    store, graph, _origins, _stats = sv_corpus_store
    dict_count = sum(1 for e in graph["edges"] if e["type"] == "checks")
    assert dict_count > 0
    assert _count_rel(store, "CHECKS") == dict_count


def test_checks_edge_is_traversable_from_assertion(sv_corpus_store) -> None:
    """A CHECKS edge is reachable in Cypher: assertion → checked signal."""
    store, _graph, _origins, _stats = sv_corpus_store
    res = store.conn.execute(
        "MATCH (a:Node)-[r:CHECKS]->(s:Node) RETURN a.kind, s.name LIMIT 1"
    )
    assert res.has_next(), "no CHECKS edge reachable in store"


def test_edge_types_registered_in_intents() -> None:
    """Query intents can route over the new edge types."""
    from knowledge_graph.query.intents import ALL_EDGE_TYPES

    assert "OF_TYPE" in ALL_EDGE_TYPES
    assert "CHECKS" in ALL_EDGE_TYPES
