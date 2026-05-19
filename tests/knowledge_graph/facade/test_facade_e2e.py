"""End-to-end tests covering every public facade entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_graph as kg
from knowledge_graph.builders.sv import extract as sv_extract


def test_open_store_and_extract(tmp_path: Path) -> None:
    store = kg.open_store(tmp_path / "kg.kuzu")
    try:
        from tests.knowledge_graph.facade.conftest import FIFO_PATHS

        stats = kg.extract(store, source="sv", corpus="fifo", paths=FIFO_PATHS)
        assert isinstance(stats, kg.ExtractStats)
        assert stats.write_stats is not None
        assert stats.write_stats.nodes_written > 0
    finally:
        store.close()


def test_query_filter_through_facade(facade_store) -> None:
    res = kg.query(
        facade_store,
        kg.FilterIntent(
            node_kind="SyntaxKind.ModuleDeclaration",
            category="semantic",
            limit=100,
        ),
    )
    names = {n.name for n in res.nodes}
    # Sanity: at least the canonical 'fifo' module is present.
    assert "fifo" in names
    assert len(res.nodes) >= 1


def test_query_traverse_through_facade(facade_store) -> None:
    res = kg.query(
        facade_store,
        kg.TraverseIntent(
            anchor=kg.AnchorRef(
                by_kind_name=("SyntaxKind.ModuleDeclaration", "fifo")
            ),
            via=["HAS_PORT"],
            depth=1,
        ),
    )
    assert res.paths, "fifo should have at least one HAS_PORT path"
    # Each path: anchor → port. The terminal node carries a port name.
    port_names = {p.nodes[-1].name for p in res.paths if len(p.nodes) >= 2}
    assert port_names, "expected named ports on fifo"


def test_cypher_through_facade(facade_store) -> None:
    res = kg.cypher(
        facade_store,
        "MATCH (n:Node) WHERE n.category = $cat RETURN count(*) AS c",
        {"cat": "semantic"},
    )
    assert res.rows
    assert res.rows[0]["c"] >= 1


def test_cypher_write_rejected(facade_store) -> None:
    with pytest.raises(kg.ReadOnlyViolation):
        kg.cypher(facade_store, "CREATE (:Node {id:'x'})")


def test_source_at_through_facade(facade_store) -> None:
    # Pick the first module node.
    res = kg.query(
        facade_store,
        kg.FilterIntent(
            node_kind="SyntaxKind.ModuleDeclaration",
            category="semantic",
            limit=1,
        ),
    )
    assert res.nodes
    n = res.nodes[0]
    assert n.span is not None and n.origin_id is not None
    bytes_from_store = kg.source_at(
        facade_store, n.origin_id, n.span.start_offset, n.span.end_offset
    )
    # Resolve original file by matching origin uri.
    uri_res = kg.cypher(
        facade_store,
        "MATCH (o:Origin) WHERE o.id = $oid RETURN o.uri AS u",
        {"oid": n.origin_id},
    )
    uri = uri_res.rows[0]["u"]
    path_str = uri.removeprefix("file://") if uri.startswith("file://") else uri
    original = Path(path_str).read_bytes()
    assert bytes_from_store == original[n.span.start_offset : n.span.end_offset]


def test_unknown_builder_raises(empty_store) -> None:
    with pytest.raises(kg.UnknownBuilder):
        kg.extract(
            empty_store, source="no-such-builder", corpus="x", paths=[Path("/tmp/x.sv")]
        )


def test_register_builder_idempotent() -> None:
    # The "sv" builder is auto-registered at import time. Re-registering the
    # same function should be a no-op.
    kg.register_builder("sv", sv_extract)
    kg.register_builder("sv", sv_extract)  # second call also a no-op


def test_register_builder_conflict() -> None:
    def fake_extract(*args, **kwargs):  # pragma: no cover - never invoked
        raise NotImplementedError

    with pytest.raises(kg.BuilderConflict):
        kg.register_builder("sv", fake_extract)


def test_extract_empty_paths_is_noop(empty_store) -> None:
    stats = kg.extract(empty_store, source="sv", corpus="fifo", paths=[])
    assert isinstance(stats, kg.ExtractStats)
    assert stats.touched_paths == []
    assert stats.unchanged_paths == []
    assert stats.write_stats is None


def test_query_before_extract_is_empty(empty_store) -> None:
    res = kg.query(empty_store, kg.FilterIntent(category="semantic"))
    assert res.nodes == []
