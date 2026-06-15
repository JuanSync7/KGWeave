"""I7-style isolation: SV-only extract doesn't touch MD, MD-only doesn't touch SV."""

from __future__ import annotations

from pathlib import Path


def _count_nodes(store, source: str) -> int:
    res = store.conn.execute(
        "MATCH (n:Node) WHERE n.source = $s RETURN count(n)",
        {"s": source},
    )
    return int(res.get_next()[0])


def test_sv_only_extract_does_not_touch_md(
    tmp_path: Path, md_fixture_dir: Path, sv_fixture_paths_for_md: list[Path]
) -> None:
    from knowledge_graph import extract, open_store

    store = open_store(tmp_path / "iso_sv.kuzu")
    md_paths = sorted(md_fixture_dir.glob("*.md"))
    extract(store, source="md", corpus="demo", paths=md_paths)
    md_before = _count_nodes(store, "md")
    assert md_before > 0

    extract(store, source="sv", corpus="demo", paths=sv_fixture_paths_for_md)
    md_after = _count_nodes(store, "md")
    assert md_after == md_before, "SV extract perturbed MD nodes"
    store.close()


def test_md_only_extract_does_not_touch_sv(
    tmp_path: Path, md_fixture_dir: Path, sv_fixture_paths_for_md: list[Path]
) -> None:
    from knowledge_graph import extract, open_store

    store = open_store(tmp_path / "iso_md.kuzu")
    extract(store, source="sv", corpus="demo", paths=sv_fixture_paths_for_md)
    sv_before = _count_nodes(store, "sv")
    assert sv_before > 0

    md_paths = sorted(md_fixture_dir.glob("*.md"))
    extract(store, source="md", corpus="demo", paths=md_paths)
    sv_after = _count_nodes(store, "sv")
    assert sv_after == sv_before, "MD extract perturbed SV nodes"
    store.close()
