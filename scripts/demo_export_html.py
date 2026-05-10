"""Run a tiny synthetic SoC through KGWeave and export an interactive HTML.

Usage:
    uv run python scripts/demo_export_html.py
"""

from __future__ import annotations

from pathlib import Path

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.types import KGConfig, load_schema
from kgweave.knowledge_graph.export.sigma_export import export_html
from kgweave.knowledge_graph.extraction import (
    SlangHierarchyAnalyzer,
    SVParserExtractor,
)


REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "config" / "kg_schema.yaml"
DEMO = REPO / "data" / "demo"
SV_FILE = DEMO / "cpu_top.sv"
FILELIST = DEMO / "files.f"
OUT_HTML = DEMO / "graph.html"


def main() -> None:
    schema = load_schema(str(SCHEMA))
    config = KGConfig()
    backend = NetworkXBackend()

    # 1) Per-file structural extraction (entities + contains/instantiates)
    parser = SVParserExtractor(schema=schema, config=config)
    text = SV_FILE.read_text()
    parsed = parser.extract(text=text, source=str(SV_FILE))
    backend.upsert_entities(parsed.entities)
    backend.upsert_triples(parsed.triples)
    print(f"parser_extractor: {len(parsed.entities)} entities, "
          f"{len(parsed.triples)} triples")

    # 2) Pyslang elaboration (hierarchy + connectivity)
    analyzer = SlangHierarchyAnalyzer(
        filelist_path=str(FILELIST),
        backend=backend,
        top_module="soc_top",
    )
    slang_result = analyzer.analyze_full()
    backend.upsert_triples(slang_result.triples)
    print(f"slang: {len(slang_result.triples)} hierarchy/connectivity triples")

    # 3) Export to interactive HTML
    n = export_html(backend=backend, output_path=str(OUT_HTML))
    print(f"\nExported {n} nodes → {OUT_HTML}")
    print(f"Open: file://{OUT_HTML}")


if __name__ == "__main__":
    main()
