"""MD builder is auto-registered under source name 'md' and produces expected kinds."""

from __future__ import annotations

from pathlib import Path

from knowledge_graph import extract, open_store


def test_md_builder_writes_expected_node_kinds(
    tmp_path: Path, md_fixture_dir: Path
) -> None:
    store = open_store(tmp_path / "md_reg.kuzu")
    md_paths = sorted(md_fixture_dir.glob("*.md"))

    stats = extract(store, source="md", corpus="md_reg", paths=md_paths)
    assert stats.write_stats is not None
    assert stats.write_stats.nodes_written > 0

    # The fixture has at minimum: a document, headings, a code fence, inline code.
    res = store.conn.execute(
        "MATCH (n:Node) WHERE n.source = 'md' RETURN DISTINCT n.kind"
    )
    kinds: set[str] = set()
    while res.has_next():
        kinds.add(res.get_next()[0])

    assert "MdDocument" in kinds
    assert "MdHeading" in kinds
    assert "MdCodeFence" in kinds
    assert "MdInlineCode" in kinds
    store.close()


def test_md_empty_paths_is_noop(tmp_path: Path) -> None:
    store = open_store(tmp_path / "md_empty.kuzu")
    stats = extract(store, source="md", corpus="md_empty", paths=[])
    # Facade no-op contract: zeroed stats, no work.
    assert stats.write_stats is None
    store.close()
