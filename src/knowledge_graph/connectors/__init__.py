"""Connector layer — small, side-effect modules that derive new edges from
existing graph contents.

Connectors run *after* extraction and operate over read-then-write
queries against a :class:`~knowledge_graph.store.KGStore`. They expose a
single :meth:`Connector.synthesize` entry point and declare which
``source`` strings they read from via :attr:`Connector.requires`.

This module ships one trivial connector — :class:`SemanticSelfRefConnector`
— used to exercise the protocol and registry end-to-end (it emits a
``CONTAINS`` self-loop for every semantic node). It has no production
utility; v1 deliberately ships no non-trivial connectors.
"""

from __future__ import annotations

from knowledge_graph.connectors.protocol import Connector

__all__ = ["Connector", "SemanticSelfRefConnector"]


class SemanticSelfRefConnector:
    """Emit a ``CONTAINS`` self-loop for every ``Node {category:'semantic'}``.

    Useless in production — purpose is to prove the connector protocol,
    registry, and write API all work end-to-end. Idempotent: a second
    run on the same store produces zero new edges (the ``MERGE`` collapses).
    """

    name: str = "semantic-self-ref"
    requires: list[str] = ["sv"]

    def synthesize(self, store) -> int:
        conn = store.conn
        res = conn.execute(
            "MATCH (n:Node) WHERE n.category = 'semantic' RETURN n.id"
        )
        ids: list[str] = []
        while res.has_next():
            ids.append(res.get_next()[0])
        for nid in ids:
            conn.execute(
                "MATCH (a:Node), (b:Node) WHERE a.id = $id AND b.id = $id "
                "MERGE (a)-[:CONTAINS]->(b)",
                {"id": nid},
            )
        return len(ids)
