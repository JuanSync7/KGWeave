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
    """Link MD inline-code / code-fence tokens to SV declarations.

    For every ``Node {source: 'md', kind in ('MdInlineCode','MdCodeFence')}``
    whose lifted ``name`` (inline-code) or contained tokens (code-fence)
    match the lifted ``name`` of an SV declaration node, emit a
    ``REFERENCES`` edge from the MD node to each matching SV node.

    Indexed SV kinds (v1.3-#5):

    * ``SyntaxKind.ModuleDeclaration`` — module names (v1.2-#6 baseline)
    * ``SyntaxKind.PackageDeclaration`` — package names
    * ``SyntaxKind.TypedefDeclaration`` — typedef names
    * ``SyntaxKind.ForwardTypedefDeclaration`` — forward typedef names
    * ``SyntaxKind.ImplicitAnsiPort`` / ``SyntaxKind.ExplicitAnsiPort`` —
      ANSI-list port names
    * ``SyntaxKind.ImplicitNonAnsiPort`` /
      ``SyntaxKind.ExplicitNonAnsiPort`` — non-ANSI-list port names

    **Corpus scoping.** SV ↔ MD matching is restricted to nodes that
    share the same ``corpus`` string. An MD node in corpus ``A`` will
    not match an SV node in corpus ``B`` even if their names coincide.

    **Disambiguation.** When the same identifier appears as multiple SV
    kinds in the same corpus (e.g. a module and a typedef both named
    ``bus``), the connector emits a separate ``REFERENCES`` edge to each
    matching SV node. The edge's ``ref_text`` column carries the matched
    name so downstream consumers can group by token. Edges are tagged
    only with the matched name — kind disambiguation comes from the
    target node's ``kind`` column.

    **Whole-token matching.** Token boundaries follow the SV identifier
    rule (alphanumeric + underscore). ``bus`` inside ``my_bus`` does not
    match.

    Idempotent: ``MERGE`` on ``(src,dst,ref_text)`` collapses duplicate
    writes from re-runs.
    """

    name: str = "sv-md-reference"
    requires: list[str] = ["sv", "md"]

    # SV kind strings indexed by this connector. Order is informational
    # only — collisions produce edges to ALL matching kinds.
    _SV_INDEXED_KINDS: tuple[str, ...] = (
        "SyntaxKind.ModuleDeclaration",
        "SyntaxKind.PackageDeclaration",
        "SyntaxKind.TypedefDeclaration",
        "SyntaxKind.ForwardTypedefDeclaration",
        "SyntaxKind.ImplicitAnsiPort",
        "SyntaxKind.ExplicitAnsiPort",
        "SyntaxKind.ImplicitNonAnsiPort",
        "SyntaxKind.ExplicitNonAnsiPort",
    )

    def synthesize(self, store) -> int:
        conn = store.conn

        # 1. Index every SV declaration of interest, keyed by corpus and name.
        #    Shape: {corpus: {name: [sv_node_id, ...]}}.
        res = conn.execute(
            """
            MATCH (s:Node)
            WHERE s.source = 'sv'
              AND s.kind IN $kinds
              AND s.name IS NOT NULL
            RETURN s.id, s.name, s.corpus
            """,
            {"kinds": list(self._SV_INDEXED_KINDS)},
        )
        sv_by_corpus: dict[str, dict[str, list[str]]] = {}
        while res.has_next():
            sid, name, corpus = res.get_next()
            if not name:
                continue
            sv_by_corpus.setdefault(corpus or "", {}).setdefault(
                name, []
            ).append(sid)
        if not sv_by_corpus:
            return 0

        # 2. Walk every MD inline-code and fence node; emit edges for hits.
        res = conn.execute(
            """
            MATCH (m:Node)
            WHERE m.source = 'md'
              AND m.kind IN ['MdInlineCode', 'MdCodeFence']
            RETURN m.id, m.kind, m.name, m.corpus
            """
        )
        md_rows: list[tuple[str, str, str, str]] = []
        while res.has_next():
            row = res.get_next()
            md_rows.append((row[0], row[1], row[2] or "", row[3] or ""))

        edges = 0
        for mid, kind, text, md_corpus in md_rows:
            sv_by_name = sv_by_corpus.get(md_corpus)
            if not sv_by_name:
                continue
            if kind == "MdInlineCode":
                # Exact match: the whole inline-code body is the candidate.
                # Tolerate trailing whitespace; require a clean identifier.
                name = text.strip()
                if name in sv_by_name:
                    for sid in sv_by_name[name]:
                        edges += self._merge_ref(conn, mid, sid, name)
            else:
                # Fence: scan tokens. We iterate every known name and
                # whole-token-match it against the fence body. This is
                # O(N_names * len(fence)) per fence which is fine for
                # the corpora we target. If this becomes a hotspot,
                # tokenise the fence once and dict-lookup instead.
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
        # in the same (md_node, sv_node) pair don't collapse. Each
        # matched name produces exactly one edge per (md, sv) pair.
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
