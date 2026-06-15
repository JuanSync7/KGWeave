"""Writer + extract tests for the Python builder.

Round-trips Python sources through KGStore via the facade's
``extract(source="py")`` dispatch and asserts (a) the expected Node
shape lands in the store, (b) PARENT_OF edges connect children to
their parent, (c) re-running on unchanged content is a no-op
(replacement-merge), and (d) changed content replaces the prior
origin subtree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


@pytest.fixture
def store_with_simple(tmp_path: Path):
    store = open_store(tmp_path / "kg.kuzu")
    extract(
        store,
        source="py",
        corpus="demo",
        paths=[FIXTURE_DIR / "simple_module.py"],
    )
    yield store
    store.close()


def test_extract_writes_nodes_with_source_py(store_with_simple) -> None:
    res = cypher(
        store_with_simple,
        "MATCH (n:Node) WHERE n.source = 'py' RETURN count(n) AS k",
    )
    k = next(iter(res.rows[0].values()))
    assert int(k) >= 5, f"expected at least 5 py nodes (mod+import+fn+cls+method), got {k}"


def test_extract_emits_function_and_class_kinds(store_with_simple) -> None:
    res = cypher(
        store_with_simple,
        """
        MATCH (n:Node) WHERE n.source = 'py' AND n.kind IN ['PyFunction','PyClass']
        RETURN n.kind AS kind, n.name AS name
        """,
    )
    pairs = {(row["kind"], row["name"]) for row in res.rows}
    assert ("PyFunction", "add") in pairs
    assert ("PyClass", "Counter") in pairs
    assert ("PyFunction", "bump") in pairs


def test_extract_creates_parent_of_edges(store_with_simple) -> None:
    """The module node parents the top-level decls; the class parents its
    methods. Verify the PARENT_OF edge set is non-trivial."""
    res = cypher(
        store_with_simple,
        """
        MATCH (a:Node)-[:PARENT_OF]->(b:Node)
        WHERE a.source = 'py' AND b.source = 'py'
        RETURN a.kind AS p, b.kind AS c
        """,
    )
    edges = [(row["p"], row["c"]) for row in res.rows]
    # Module parents the import, the top function, the class.
    assert ("PyModule", "PyFunction") in edges
    assert ("PyModule", "PyClass") in edges
    # Class parents its methods.
    assert ("PyClass", "PyFunction") in edges


def test_extract_unchanged_is_idempotent(tmp_path: Path) -> None:
    """Re-running extract on identical content emits zero new nodes."""
    store = open_store(tmp_path / "kg.kuzu")
    p = FIXTURE_DIR / "simple_module.py"
    extract(store, source="py", corpus="demo", paths=[p])
    res1 = cypher(store, "MATCH (n:Node) WHERE n.source='py' RETURN count(n) AS k")
    n1 = int(next(iter(res1.rows[0].values())))

    stats2 = extract(store, source="py", corpus="demo", paths=[p])
    res2 = cypher(store, "MATCH (n:Node) WHERE n.source='py' RETURN count(n) AS k")
    n2 = int(next(iter(res2.rows[0].values())))

    assert n1 == n2
    assert stats2.touched_paths == []  # nothing changed -> nothing touched
    assert stats2.unchanged_paths  # the file was logged as unchanged
    store.close()


def test_extract_replaces_subtree_on_content_change(tmp_path: Path) -> None:
    """Replacement-merge: a content change deletes the old subtree."""
    store = open_store(tmp_path / "kg.kuzu")
    p = tmp_path / "mutable.py"
    p.write_text("def alpha(): pass\n")
    extract(store, source="py", corpus="demo", paths=[p])
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyFunction' RETURN n.name AS n",
    )
    assert {row["n"] for row in res.rows} == {"alpha"}

    p.write_text("def beta(): pass\n")
    extract(store, source="py", corpus="demo", paths=[p])
    res = cypher(
        store,
        "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyFunction' RETURN n.name AS n",
    )
    assert {row["n"] for row in res.rows} == {"beta"}
    store.close()
