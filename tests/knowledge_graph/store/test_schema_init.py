"""Schema-init smoke tests: every table from the plan must exist."""

from __future__ import annotations

EXPECTED_NODE_TABLES = {"Origin", "Node", "BlobPayload"}

EXPECTED_REL_TABLES = {
    "PARENT_OF",
    "CONTAINS",
    "DRIVES",
    "READS",
    "SENSITIVE_TO",
    "INSTANTIATES",
    "OF_MODULE",
    "CONNECTS",
    "PARAM_OVERRIDE",
    "CALLS",
    "HAS_PORT",
    "HAS_PARAM",
    "HAS_NET",
    "HAS_TYPEDEF",
    "HAS_ENUM_VALUE",
    "HAS_MODPORT",
    "HAS_FUNCTION",
    "HAS_GENERATE",
    "CONTAINS_BLOCK",
    "IN_ORIGIN",
    "HAS_PAYLOAD",
}


def _table_names(store) -> dict[str, str]:
    res = store.conn.execute("CALL show_tables() RETURN *")
    out: dict[str, str] = {}
    while res.has_next():
        row = res.get_next()
        # show_tables() returns columns: id, name, type, ... (varies by Kuzu version)
        name = None
        ttype = None
        for cell in row:
            if isinstance(cell, str):
                if cell in {"NODE", "REL"}:
                    ttype = cell
                elif name is None:
                    # first string-ish column that isn't NODE/REL
                    name = cell
        if name is None:
            continue
        out[name] = ttype or ""
    return out


def test_schema_creates_all_node_tables(tmp_store):
    """Initialising the store must create Origin, Node, BlobPayload tables."""
    tables = _table_names(tmp_store)
    missing = EXPECTED_NODE_TABLES - set(tables)
    assert not missing, f"missing node tables: {missing}"


def test_schema_creates_all_rel_tables(tmp_store):
    """Initialising the store must create every rel table named in the plan."""
    tables = _table_names(tmp_store)
    missing = EXPECTED_REL_TABLES - set(tables)
    assert not missing, f"missing rel tables: {missing}"


def test_schema_init_is_idempotent(tmp_path):
    """Re-opening an existing store must not raise (tables already exist)."""
    from knowledge_graph.store import KGStore

    db_path = tmp_path / "kg.kuzu"
    s1 = KGStore.open(db_path)
    s1.close()
    s2 = KGStore.open(db_path)
    try:
        tables = _table_names(s2)
        assert "Origin" in tables
        assert "PARENT_OF" in tables
    finally:
        s2.close()
