"""SvMarkdownReferenceConnector links MD inline-code / code-fence tokens to SV modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph import (
    ConnectorRequirementError,
    SvMarkdownReferenceConnector,
    cypher,
    extract,
    open_store,
    register_connector,
    run_connectors,
)


SV_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "sv"
)
MD_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "builders" / "md" / "fixtures"
)


@pytest.fixture(scope="module", autouse=True)
def _register_connector() -> None:
    register_connector(SvMarkdownReferenceConnector())


def _setup_store(path: Path) -> object:
    store = open_store(path)
    sv_paths = [SV_FIXTURE_DIR / "fifo.sv", SV_FIXTURE_DIR / "fifo_pkg.sv"]
    extract(store, source="sv", corpus="demo", paths=sv_paths)
    md_paths = sorted(MD_FIXTURE_DIR.glob("*.md"))
    extract(store, source="md", corpus="demo", paths=md_paths)
    return store


def test_connector_creates_references_to_known_sv_module(tmp_path: Path) -> None:
    store = _setup_store(tmp_path / "kg.kuzu")
    counts = run_connectors(store, only=["sv-md-reference"])
    assert counts["sv-md-reference"] > 0

    res = cypher(
        store,
        """
        MATCH (m:Node)-[r:REFERENCES]->(s:Node)
        WHERE m.source = 'md' AND s.source = 'sv'
        RETURN s.name AS name, count(*) AS k
        """,
    )
    names = {row["name"]: int(row["k"]) for row in res.rows}
    assert "fifo" in names
    assert names["fifo"] >= 2  # fixture mentions `fifo` multiple times
    store.close()


def test_connector_skips_unknown_module_names(tmp_path: Path) -> None:
    store = _setup_store(tmp_path / "kg.kuzu")
    run_connectors(store, only=["sv-md-reference"])

    # No edge should target `nonexistent_module` (it has no SV module).
    res = cypher(
        store,
        """
        MATCH (m:Node)-[:REFERENCES]->(s:Node)
        WHERE m.source = 'md' AND s.source = 'sv' AND s.name = 'nonexistent_module'
        RETURN count(*)
        """,
    )
    row = res.rows[0]
    # Kuzu emits aggregate result columns under their expression text.
    only_val = next(iter(row.values()))
    assert int(only_val) == 0
    store.close()


def test_connector_idempotent_on_rerun(tmp_path: Path) -> None:
    store = _setup_store(tmp_path / "kg.kuzu")
    first = run_connectors(store, only=["sv-md-reference"])
    res1 = store.conn.execute(
        "MATCH (m:Node)-[r:REFERENCES]->(s:Node) "
        "WHERE m.source = 'md' AND s.source = 'sv' RETURN count(r)"
    )
    n1 = int(res1.get_next()[0])

    run_connectors(store, only=["sv-md-reference"])
    res2 = store.conn.execute(
        "MATCH (m:Node)-[r:REFERENCES]->(s:Node) "
        "WHERE m.source = 'md' AND s.source = 'sv' RETURN count(r)"
    )
    n2 = int(res2.get_next()[0])
    assert n1 == n2 == first["sv-md-reference"]
    store.close()


def test_connector_zero_edges_when_md_has_no_known_refs(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    sv_paths = [SV_FIXTURE_DIR / "fifo.sv"]
    extract(store, source="sv", corpus="demo", paths=sv_paths)
    # Only the file without any known module name.
    extract(
        store,
        source="md",
        corpus="demo",
        paths=[MD_FIXTURE_DIR / "empty_refs.md"],
    )
    counts = run_connectors(store, only=["sv-md-reference"])
    assert counts["sv-md-reference"] == 0
    store.close()


def test_connector_requires_both_builders(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    extract(store, source="md", corpus="demo", paths=[MD_FIXTURE_DIR / "fifo_notes.md"])
    with pytest.raises(ConnectorRequirementError):
        run_connectors(store, only=["sv-md-reference"])
    store.close()
