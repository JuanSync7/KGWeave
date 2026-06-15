"""Multi-file Python extract — both files end up in the same store
with disjoint origins.

The v1 builder has no cross-file semantic pass (no SV-style
``_unresolved.*`` placeholders for Python imports). The cross-file
linking is left to the Python ↔ MD connector and a future Python-only
import-resolution connector. What this test pins down is the
structural property: each file becomes its own origin subtree, and the
PyImport node in ``multi_file_b`` records the imported names in its
payload so a future connector can resolve them.
"""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


def test_multi_file_extract_creates_two_origins(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    extract(
        store,
        source="py",
        corpus="demo",
        paths=[
            FIXTURE_DIR / "multi_file_a.py",
            FIXTURE_DIR / "multi_file_b.py",
        ],
    )
    res = cypher(
        store,
        "MATCH (o:Origin) WHERE o.source='py' RETURN count(o) AS k",
    )
    assert int(next(iter(res.rows[0].values()))) == 2
    store.close()


def test_multi_file_b_import_payload_records_a_symbols(tmp_path: Path) -> None:
    """``multi_file_b`` imports Widget + make_widget from multi_file_a;
    the PyImport node's payload must carry those names so the future
    cross-file connector can resolve them by name."""
    store = open_store(tmp_path / "kg.kuzu")
    extract(
        store,
        source="py",
        corpus="demo",
        paths=[
            FIXTURE_DIR / "multi_file_a.py",
            FIXTURE_DIR / "multi_file_b.py",
        ],
    )
    res = cypher(
        store,
        """
        MATCH (n:Node) WHERE n.source='py' AND n.kind='PyImport'
        RETURN n.name AS module, n.payload AS payload, n.origin_id AS origin_id
        """,
    )
    # Find the PyImport in multi_file_b -- module name == 'multi_file_a'.
    from_a = [row for row in res.rows if row["module"] == "multi_file_a"]
    assert from_a, "expected a PyImport whose module is multi_file_a"
    payload = json.loads(from_a[0]["payload"])
    names_set = set(payload["payload"]["names"])
    assert {"Widget", "make_widget"}.issubset(names_set)
    store.close()


def test_multi_file_a_and_b_have_disjoint_origin_ids(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    extract(
        store,
        source="py",
        corpus="demo",
        paths=[
            FIXTURE_DIR / "multi_file_a.py",
            FIXTURE_DIR / "multi_file_b.py",
        ],
    )
    res = cypher(
        store,
        """
        MATCH (n:Node) WHERE n.source='py' AND n.kind='PyModule'
        RETURN n.name AS name, n.origin_id AS oid
        """,
    )
    by_name = {row["name"]: row["oid"] for row in res.rows}
    assert set(by_name) == {"multi_file_a", "multi_file_b"}
    assert by_name["multi_file_a"] != by_name["multi_file_b"]
    store.close()
