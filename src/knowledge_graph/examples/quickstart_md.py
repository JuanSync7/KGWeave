"""End-to-end MD + SV + connector example.

Run with::

    python -m knowledge_graph.examples.quickstart_md [store_dir]

Demonstrates the v1.2 multi-builder story:

1. Extract SV from the canonical fixture corpus.
2. Extract markdown from a fixture set under
   ``tests/knowledge_graph/builders/md/fixtures``.
3. Register the SV-MD reference connector and run it.
4. Query the resulting cross-builder ``REFERENCES`` edges.
"""

from __future__ import annotations

import sys
from pathlib import Path

from knowledge_graph import (
    SvMarkdownReferenceConnector,
    cypher,
    extract,
    open_store,
    register_connector,
    run_connectors,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    store_path = (
        Path(argv[0]) if argv else Path("./kgweave-store/quickstart_md.kuzu")
    )

    repo = _repo_root()
    sv_dir = repo / "tests" / "knowledge_graph" / "fixtures" / "sv"
    md_dir = repo / "tests" / "knowledge_graph" / "builders" / "md" / "fixtures"

    store = open_store(store_path)

    sv_stats = extract(
        store,
        source="sv",
        corpus="demo",
        paths=[sv_dir / "fifo.sv", sv_dir / "fifo_pkg.sv"],
    )
    print(
        f"sv extract: touched={len(sv_stats.touched_paths)} "
        f"nodes={(sv_stats.write_stats.nodes_written if sv_stats.write_stats else 0)}"
    )

    md_stats = extract(
        store,
        source="md",
        corpus="demo",
        paths=sorted(md_dir.glob("*.md")),
    )
    print(
        f"md extract: touched={len(md_stats.touched_paths)} "
        f"nodes={(md_stats.write_stats.nodes_written if md_stats.write_stats else 0)}"
    )

    register_connector(SvMarkdownReferenceConnector())
    counts = run_connectors(store, only=["sv-md-reference"])
    print(f"connector edges written: {counts}")

    refs = cypher(
        store,
        """
        MATCH (m:Node)-[r:REFERENCES]->(s:Node)
        WHERE m.source = 'md' AND s.source = 'sv'
        RETURN m.kind, m.name, s.name, r.ref_text
        ORDER BY s.name, m.start_offset
        """,
    )
    print(f"cross-builder REFERENCES rows: {len(refs.rows)}")
    for row in refs.rows[:20]:
        print(f"  md.{row['m.kind']} ({row['m.name']!r}) -> sv:{row['s.name']}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
