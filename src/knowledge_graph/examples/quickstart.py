"""End-to-end quickstart: open store → extract SV → query → raw Cypher.

Run with::

    python -m knowledge_graph.examples.quickstart [store_dir] [fixture_dir]

Both arguments are optional. Defaults: ``./kgweave-store/quickstart.kuzu``
for the store path, and ``tests/knowledge_graph/fixtures/sv`` for the
fixture corpus (resolved relative to the repository root).
"""

from __future__ import annotations

import sys
from pathlib import Path

from knowledge_graph import (
    AnchorRef,
    FilterIntent,
    TraverseIntent,
    cypher,
    extract,
    open_store,
    query,
    source_at,
)


def _default_fixture_dir() -> Path:
    here = Path(__file__).resolve()
    # src/knowledge_graph/examples/quickstart.py → up 3 to repo root.
    repo_root = here.parents[3]
    return repo_root / "tests" / "knowledge_graph" / "fixtures" / "sv"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    store_path = Path(argv[0]) if argv else Path("./kgweave-store/quickstart.kuzu")
    fixture_dir = Path(argv[1]) if len(argv) > 1 else _default_fixture_dir()

    paths = [fixture_dir / "fifo.sv", fixture_dir / "fifo_pkg.sv"]

    store = open_store(store_path)

    stats = extract(store, source="sv", corpus="fifo", paths=paths)
    print(
        f"extract: touched={len(stats.touched_paths)} "
        f"unchanged={len(stats.unchanged_paths)} "
        f"nodes_written={(stats.write_stats.nodes_written if stats.write_stats else 0)}"
    )

    modules = query(
        store,
        FilterIntent(
            node_kind="SyntaxKind.ModuleDeclaration",
            category="semantic",
            limit=20,
        ),
    )
    print(f"modules: count={len(modules.nodes)}")
    for m in modules.nodes:
        print(f"  module id={m.id} name={m.name}")
        if m.span is not None and m.origin_id:
            src = source_at(
                store, m.origin_id, m.span.start_offset, m.span.end_offset
            )
            snippet = src[:80].decode("utf-8", errors="replace").replace("\n", " ")
            print(f"    span[0:80]={snippet!r}")

    if modules.nodes:
        first_name = modules.nodes[0].name or ""
        ports = query(
            store,
            TraverseIntent(
                anchor=AnchorRef(
                    by_kind_name=("SyntaxKind.ModuleDeclaration", first_name)
                ),
                via=["HAS_PORT"],
                depth=1,
            ),
        )
        print(f"ports of {first_name!r}: paths={len(ports.paths)}")
        for p in ports.paths[:5]:
            print("  path:", [(n.name, n.kind) for n in p.nodes])

    raw = cypher(
        store,
        "MATCH (n:Node) WHERE n.category = $cat RETURN count(*) AS c",
        {"cat": "semantic"},
    )
    print(f"raw cypher rows: {raw.rows}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
