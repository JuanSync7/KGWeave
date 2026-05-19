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

__all__ = [
    "Connector",
    "SemanticSelfRefConnector",
    "SvMarkdownReferenceConnector",
]


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


class SvMarkdownReferenceConnector:
    """Link MD inline-code / code-fence tokens to SV module declarations.

    For every ``Node {source: 'md', kind in ('MdInlineCode','MdCodeFence')}``
    whose lifted ``name`` matches the name of some
    ``Node {source: 'sv', kind: 'SyntaxKind.ModuleDeclaration'}``, emit a
    ``REFERENCES`` edge from the MD node to the SV module node.

    For code-fence content (multi-line), every backtick-free identifier
    token that matches a known module name produces a separate edge —
    but v1 keeps it simple: we match the *entire* fence body via
    substring scan against known module names, emitting at most one edge
    per (md_node, sv_module) pair. Repeat occurrences across distinct MD
    inline-code nodes naturally produce distinct edges (they have
    distinct source ids).

    Idempotent: ``MERGE`` on ``(src,dst,ref_text)`` collapses duplicate
    writes from re-runs.
    """

    name: str = "sv-md-reference"
    requires: list[str] = ["sv", "md"]

    # Stable kind string used by the SV builder for module declarations.
    _SV_MODULE_KIND: str = "SyntaxKind.ModuleDeclaration"

    def synthesize(self, store) -> int:
        conn = store.conn

        # 1. Index every SV module's (name -> [node_id]).
        res = conn.execute(
            """
            MATCH (s:Node)
            WHERE s.source = 'sv' AND s.kind = $kind AND s.name IS NOT NULL
            RETURN s.id, s.name
            """,
            {"kind": self._SV_MODULE_KIND},
        )
        sv_by_name: dict[str, list[str]] = {}
        while res.has_next():
            sid, name = res.get_next()
            if name:
                sv_by_name.setdefault(name, []).append(sid)
        if not sv_by_name:
            return 0

        # 2. Walk every MD inline-code and fence node; emit edges for hits.
        res = conn.execute(
            """
            MATCH (m:Node)
            WHERE m.source = 'md'
              AND m.kind IN ['MdInlineCode', 'MdCodeFence']
            RETURN m.id, m.kind, m.name
            """
        )
        md_rows: list[tuple[str, str, str]] = []
        while res.has_next():
            row = res.get_next()
            md_rows.append((row[0], row[1], row[2] or ""))

        edges = 0
        for mid, kind, text in md_rows:
            if kind == "MdInlineCode":
                # Exact match: the whole inline-code body is the candidate.
                name = text.strip()
                if name in sv_by_name:
                    for sid in sv_by_name[name]:
                        edges += self._merge_ref(conn, mid, sid, name)
            else:
                # Fence: substring scan for every known module name.
                # Token-boundary check is a simple non-alnum/_ guard so we
                # don't match `fifo` inside `myfifo_top`.
                for name in sv_by_name:
                    if self._token_in(text, name):
                        for sid in sv_by_name[name]:
                            edges += self._merge_ref(conn, mid, sid, name)
        return edges

    @staticmethod
    def _token_in(haystack: str, needle: str) -> bool:
        idx = 0
        n = len(needle)
        while True:
            j = haystack.find(needle, idx)
            if j < 0:
                return False
            left_ok = j == 0 or not (
                haystack[j - 1].isalnum() or haystack[j - 1] == "_"
            )
            right = j + n
            right_ok = right >= len(haystack) or not (
                haystack[right].isalnum() or haystack[right] == "_"
            )
            if left_ok and right_ok:
                return True
            idx = j + 1

    @staticmethod
    def _merge_ref(conn, mid: str, sid: str, ref_text: str) -> int:
        # MERGE pattern: ref_text becomes a key column so distinct names
        # in the same (md_node, sv_module) pair don't collapse — though
        # for this connector each MD node maps to at most one name.
        conn.execute(
            """
            MATCH (a:Node {id: $src}), (b:Node {id: $dst})
            MERGE (a)-[r:REFERENCES {ref_text: $ref_text}]->(b)
            ON CREATE SET r.ordinal = 0
            ON MATCH SET r.ordinal = 0
            """,
            {"src": mid, "dst": sid, "ref_text": ref_text},
        )
        return 1
