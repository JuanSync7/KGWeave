"""PyMarkdownReferenceConnector — link MD inline-code / code-fence tokens
to Python declarations (modules / functions / classes / imports).

Mirrors the SV ↔ MD connector but indexes the Python kinds. Uses
``build_name_index`` from the shared helper module (v1.5-#3 G1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph import (
    cypher,
    extract,
    open_store,
    register_connector,
    run_connectors,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "py"


@pytest.fixture(scope="module", autouse=True)
def _register_py_md_connector() -> None:
    """Register :class:`PyMarkdownReferenceConnector` once per module.

    The registry is same-class idempotent (v1.5-#5), so registering
    from multiple test modules in the same session is a no-op.
    """
    from knowledge_graph.connectors.py_md import PyMarkdownReferenceConnector

    register_connector(PyMarkdownReferenceConnector())


def _setup_store(path: Path):
    store = open_store(path)
    extract(
        store,
        source="py",
        corpus="pymd",
        paths=[FIXTURE_DIR / "simple_module.py"],
    )
    extract(
        store,
        source="md",
        corpus="pymd",
        paths=[FIXTURE_DIR / "py_refs.md"],
    )
    return store


def test_connector_links_inline_code_to_py_function(tmp_path: Path) -> None:
    store = _setup_store(tmp_path / "kg.kuzu")
    counts = run_connectors(store, only=["py-md-reference"])
    assert counts["py-md-reference"] > 0
    res = cypher(
        store,
        """
        MATCH (m:Node)-[:REFERENCES]->(p:Node)
        WHERE m.source='md' AND p.source='py' AND p.name='add'
        RETURN count(*) AS k
        """,
    )
    k = int(next(iter(res.rows[0].values())))
    assert k >= 1
    store.close()


def test_connector_links_to_py_class(tmp_path: Path) -> None:
    store = _setup_store(tmp_path / "kg.kuzu")
    run_connectors(store, only=["py-md-reference"])
    res = cypher(
        store,
        """
        MATCH (m:Node)-[:REFERENCES]->(p:Node)
        WHERE m.source='md' AND p.source='py' AND p.name='Counter'
        RETURN count(*) AS k
        """,
    )
    assert int(next(iter(res.rows[0].values()))) >= 1
    store.close()


def test_connector_skips_unknown_symbol(tmp_path: Path) -> None:
    store = _setup_store(tmp_path / "kg.kuzu")
    run_connectors(store, only=["py-md-reference"])
    res = cypher(
        store,
        """
        MATCH (m:Node)-[:REFERENCES]->(p:Node)
        WHERE m.source='md' AND p.source='py' AND p.name='not_a_real_symbol'
        RETURN count(*) AS k
        """,
    )
    assert int(next(iter(res.rows[0].values()))) == 0
    store.close()


def test_connector_is_idempotent(tmp_path: Path) -> None:
    store = _setup_store(tmp_path / "kg.kuzu")
    first = run_connectors(store, only=["py-md-reference"])
    second = run_connectors(store, only=["py-md-reference"])
    # Edge counts identical across runs (MERGE collapses duplicate writes).
    res = cypher(
        store,
        """
        MATCH (m:Node)-[r:REFERENCES]->(p:Node)
        WHERE m.source='md' AND p.source='py' RETURN count(r) AS k
        """,
    )
    k = int(next(iter(res.rows[0].values())))
    assert k == first["py-md-reference"] == second["py-md-reference"]
    store.close()


def test_connector_corpus_scoped(tmp_path: Path) -> None:
    """A Python decl in corpus A is invisible to an MD token in corpus B."""
    store = open_store(tmp_path / "kg.kuzu")
    extract(
        store,
        source="py",
        corpus="corpA",
        paths=[FIXTURE_DIR / "simple_module.py"],
    )
    extract(
        store,
        source="md",
        corpus="corpB",
        paths=[FIXTURE_DIR / "py_refs.md"],
    )
    run_connectors(store, only=["py-md-reference"])
    res = cypher(
        store,
        """
        MATCH (m:Node)-[:REFERENCES]->(p:Node)
        WHERE m.source='md' AND p.source='py' RETURN count(*) AS k
        """,
    )
    assert int(next(iter(res.rows[0].values()))) == 0
    store.close()
