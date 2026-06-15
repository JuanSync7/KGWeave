"""Python ↔ Markdown reference connector.

Mirrors :class:`SvMarkdownReferenceConnector` but indexes Python
declarations instead of SV ones. Reuses
:func:`knowledge_graph.connectors._name_index.build_name_index` to
group ``(id, name, corpus)`` rows -- no duplication of the SV grouping
loop (v1.5-#3 G1 pre-req).

Indexed Python kinds:

* ``PyModule``   -- the file-level node; matches an MD token whose
                    body equals the module's basename stem.
* ``PyFunction`` -- every ``def`` (top-level / nested / method).
* ``PyClass``    -- every ``class`` body.
* ``PyImport``   -- ``import x`` and ``from x import y`` rows; the
                    ``name`` is the source module (``x``).

Whole-token matching: token boundaries follow the Python identifier
rule (alphanumeric + underscore). ``add`` inside ``my_add_func`` does
not match.

Corpus scoping + disambiguation are identical to the SV ↔ MD
connector. Idempotent via MERGE on ``(src, dst, ref_text)``.
"""

from __future__ import annotations

from knowledge_graph.connectors._name_index import build_name_index


# Python kinds indexed by this connector. The Python builder writes
# these as category='semantic' so a future optimisation could
# down-select on n.category, but here we filter by kind for symmetry
# with the SV connector.
PY_INDEXED_KINDS: tuple[str, ...] = (
    "PyModule",
    "PyFunction",
    "PyClass",
    "PyImport",
)


class PyMarkdownReferenceConnector:
    """Link MD inline-code / code-fence tokens to Python declarations.

    For every ``Node {source: 'md', kind in ('MdInlineCode','MdCodeFence')}``
    whose lifted ``name`` (inline-code) or contained tokens (code-fence)
    match a Python declaration's ``name``, emit a ``REFERENCES`` edge
    from the MD node to each matching Python node.

    Token boundaries follow the Python identifier rule
    (alphanumeric + underscore). Edges carry the matched name as
    ``ref_text`` so downstream consumers can group by token; the target
    node's ``kind`` column disambiguates collisions across kinds.

    Idempotent: ``MERGE`` on ``(src, dst, ref_text)`` collapses
    duplicate writes from re-runs.
    """

    name: str = "py-md-reference"
    requires: list[str] = ["py", "md"]

    _PY_INDEXED_KINDS: tuple[str, ...] = PY_INDEXED_KINDS

    def synthesize(self, store) -> int:
        conn = store.conn

        res = conn.execute(
            """
            MATCH (s:Node)
            WHERE s.source = 'py'
              AND s.kind IN $kinds
              AND s.name IS NOT NULL
            RETURN s.id, s.name, s.corpus
            """,
            {"kinds": list(self._PY_INDEXED_KINDS)},
        )
        rows: list[tuple[str, str | None, str | None]] = []
        while res.has_next():
            row = res.get_next()
            rows.append((row[0], row[1], row[2]))
        py_by_corpus = build_name_index(rows)
        if not py_by_corpus:
            return 0

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
            py_by_name = py_by_corpus.get(md_corpus)
            if not py_by_name:
                continue
            if kind == "MdInlineCode":
                name = text.strip()
                if name in py_by_name:
                    for pid in py_by_name[name]:
                        edges += self._merge_ref(conn, mid, pid, name)
            else:
                # Fence: O(N_names * len(fence)) — fine for our corpora.
                for name in py_by_name:
                    if self._token_in(text, name):
                        for pid in py_by_name[name]:
                            edges += self._merge_ref(conn, mid, pid, name)
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
    def _merge_ref(conn, mid: str, pid: str, ref_text: str) -> int:
        conn.execute(
            """
            MATCH (a:Node {id: $src}), (b:Node {id: $dst})
            MERGE (a)-[r:REFERENCES {ref_text: $ref_text}]->(b)
            ON CREATE SET r.ordinal = 0
            ON MATCH SET r.ordinal = 0
            """,
            {"src": mid, "dst": pid, "ref_text": ref_text},
        )
        return 1


__all__ = ["PyMarkdownReferenceConnector", "PY_INDEXED_KINDS"]
