# @summary
# Tests for MarkdownDocExtractor — section extraction, RTL doc fusion,
# code-span exclusion, references edges, and extractor_source attribution.
# @end-summary
"""TDD coverage for the markdown documentation extractor."""

from __future__ import annotations

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Entity
from kgweave.knowledge_graph.extraction.markdown_doc_extractor import (
    MarkdownDocExtractor,
)


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------


def test_section_entities_extracted() -> None:
    """h1/h2/h3 headers each become Section entities with slugged anchor names."""
    md = "# Top\n\nintro paragraph.\n\n## Inner\n\ndetail.\n"
    extractor = MarkdownDocExtractor()
    result = extractor.extract(md, source="theory_of_operation.md")

    sections = [e for e in result.entities if e.type == "Section"]
    assert len(sections) == 2

    names = {e.name for e in sections}
    assert "theory_of_operation.md#top" in names
    assert "theory_of_operation.md#inner" in names

    for sec in sections:
        assert sec.sources == ["theory_of_operation.md"]
        assert sec.extractor_source == ["markdown_doc"]


# ---------------------------------------------------------------------------
# Doc fusion with existing RTL_Module
# ---------------------------------------------------------------------------


def test_module_reference_fuses_with_existing_rtl_module() -> None:
    """An existing RTL_Module entity gains the doc file in its sources list."""
    backend = NetworkXBackend()
    backend.upsert_entities(
        [Entity(name="aes_core", type="RTL_Module", sources=["rtl/aes_core.sv"])]
    )

    md = (
        "# Theory of Operation\n\n"
        "The aes_core module performs AES-128 rounds.\n"
    )
    extractor = MarkdownDocExtractor(
        known_entity_names=backend.get_all_node_names_and_aliases().values()
    )
    result = extractor.extract(md, source="theory_of_operation.md")

    # The extractor must emit a fusion entity for aes_core.
    fusion_names = {e.name for e in result.entities if e.type == "RTL_Module"}
    assert "aes_core" in fusion_names

    # Upserting must fuse — the existing RTL_Module gains the doc file.
    backend.upsert_entities(result.entities)

    fused = backend.get_entity("aes_core")
    assert fused is not None
    assert fused.type == "RTL_Module"  # type was NOT overwritten
    assert "rtl/aes_core.sv" in fused.sources
    assert "theory_of_operation.md" in fused.sources


# ---------------------------------------------------------------------------
# Code-span exclusion
# ---------------------------------------------------------------------------


def test_module_reference_skips_code_spans() -> None:
    """Mentions wrapped in backticks (code spans) must not produce fusion entities."""
    md = "# Guide\n\nUse the `aes_core` macro carefully.\n"
    extractor = MarkdownDocExtractor(known_entity_names=["aes_core"])
    result = extractor.extract(md, source="programmers_guide.md")

    fusion = [e for e in result.entities if e.type == "RTL_Module"]
    assert fusion == []


# ---------------------------------------------------------------------------
# References edges between sections
# ---------------------------------------------------------------------------


def test_references_edge_for_markdown_links() -> None:
    """An in-doc link from a section to another anchor emits a references triple."""
    md = (
        "# Overview\n\n"
        "[See block diagram](#block-diagram) for details.\n\n"
        "## Block Diagram\n\n"
        "diagram body.\n"
    )
    extractor = MarkdownDocExtractor()
    result = extractor.extract(md, source="theory_of_operation.md")

    refs = [t for t in result.triples if t.predicate == "references"]
    assert len(refs) >= 1

    triple = refs[0]
    assert triple.subject == "theory_of_operation.md#overview"
    assert triple.object == "theory_of_operation.md#block-diagram"


# ---------------------------------------------------------------------------
# Extractor-source attribution
# ---------------------------------------------------------------------------


def test_extractor_source_attribution() -> None:
    """Every emitted triple must carry extractor_source='markdown_doc'."""
    md = (
        "# Overview\n\n"
        "[See block diagram](#block-diagram).\n\n"
        "## Block Diagram\n\n"
        "body.\n"
    )
    extractor = MarkdownDocExtractor()
    result = extractor.extract(md, source="theory_of_operation.md")

    assert result.triples, "expected at least one triple"
    for t in result.triples:
        assert t.extractor_source == "markdown_doc"
    for e in result.entities:
        assert e.extractor_source == ["markdown_doc"]
