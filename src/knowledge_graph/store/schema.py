"""Base-schema DDL for the KGWeave Kuzu store.

The DDL strings mirror ``docs/plans/KUZU_PORT_PLAN.md`` exactly. Phase A
creates the node + rel tables but does **not** populate ``Node`` rows —
that lands in Phase C.

``content`` on ``Origin`` is declared as ``STRING``: Kuzu's parameter
binding rejects ``bytes`` outright, but ``STRING`` parameters round-trip
arbitrary bytes (including NULs) when the Python side encodes/decodes via
``latin-1`` (see ``snapshot.py`` / ``spans.py``). We keep the column type
aligned with the plan and document the encoding contract instead.
"""

from __future__ import annotations

from typing import Iterable

NODE_TABLES: tuple[tuple[str, str], ...] = (
    (
        "Origin",
        """
        CREATE NODE TABLE IF NOT EXISTS Origin (
            id STRING,
            uri STRING,
            sha256 STRING,
            content STRING,
            byte_length INT64,
            source STRING,
            corpus STRING,
            lang STRING,
            extracted_at TIMESTAMP,
            PRIMARY KEY (id)
        )
        """,
    ),
    (
        "Node",
        """
        CREATE NODE TABLE IF NOT EXISTS Node (
            id STRING,
            kind STRING,
            category STRING,
            name STRING,
            source STRING,
            corpus STRING,
            origin_id STRING,
            start_offset INT64,
            end_offset INT64,
            start_line INT32,
            end_line INT32,
            start_col INT32,
            end_col INT32,
            payload STRING,
            PRIMARY KEY (id)
        )
        """,
    ),
    (
        "BlobPayload",
        """
        CREATE NODE TABLE IF NOT EXISTS BlobPayload (
            sha256 STRING,
            json STRING,
            PRIMARY KEY (sha256)
        )
        """,
    ),
)


REL_TABLES: tuple[tuple[str, str], ...] = (
    ("PARENT_OF",       "CREATE REL TABLE IF NOT EXISTS PARENT_OF (FROM Node TO Node, ordinal INT32)"),
    ("CONTAINS",        "CREATE REL TABLE IF NOT EXISTS CONTAINS (FROM Node TO Node)"),
    ("DRIVES",          "CREATE REL TABLE IF NOT EXISTS DRIVES (FROM Node TO Node)"),
    ("READS",           "CREATE REL TABLE IF NOT EXISTS READS (FROM Node TO Node)"),
    ("SENSITIVE_TO",    "CREATE REL TABLE IF NOT EXISTS SENSITIVE_TO (FROM Node TO Node, edge STRING)"),
    ("INSTANTIATES",    "CREATE REL TABLE IF NOT EXISTS INSTANTIATES (FROM Node TO Node)"),
    ("OF_MODULE",       "CREATE REL TABLE IF NOT EXISTS OF_MODULE (FROM Node TO Node)"),
    ("CONNECTS",        "CREATE REL TABLE IF NOT EXISTS CONNECTS (FROM Node TO Node, instance STRING, port STRING)"),
    ("PARAM_OVERRIDE",  "CREATE REL TABLE IF NOT EXISTS PARAM_OVERRIDE (FROM Node TO Node, name STRING, value STRING)"),
    ("CALLS",           "CREATE REL TABLE IF NOT EXISTS CALLS (FROM Node TO Node)"),
    ("HAS_PORT",        "CREATE REL TABLE IF NOT EXISTS HAS_PORT (FROM Node TO Node)"),
    ("HAS_PARAM",       "CREATE REL TABLE IF NOT EXISTS HAS_PARAM (FROM Node TO Node)"),
    ("HAS_NET",         "CREATE REL TABLE IF NOT EXISTS HAS_NET (FROM Node TO Node)"),
    ("HAS_TYPEDEF",     "CREATE REL TABLE IF NOT EXISTS HAS_TYPEDEF (FROM Node TO Node)"),
    ("HAS_ENUM_VALUE",  "CREATE REL TABLE IF NOT EXISTS HAS_ENUM_VALUE (FROM Node TO Node, name STRING, typedef STRING)"),
    ("HAS_MODPORT",     "CREATE REL TABLE IF NOT EXISTS HAS_MODPORT (FROM Node TO Node)"),
    ("HAS_FUNCTION",    "CREATE REL TABLE IF NOT EXISTS HAS_FUNCTION (FROM Node TO Node)"),
    ("HAS_GENERATE",    "CREATE REL TABLE IF NOT EXISTS HAS_GENERATE (FROM Node TO Node)"),
    ("CONTAINS_BLOCK",  "CREATE REL TABLE IF NOT EXISTS CONTAINS_BLOCK (FROM Node TO Node)"),
    ("IN_ORIGIN",       "CREATE REL TABLE IF NOT EXISTS IN_ORIGIN (FROM Node TO Origin)"),
    ("HAS_PAYLOAD",     "CREATE REL TABLE IF NOT EXISTS HAS_PAYLOAD (FROM Node TO BlobPayload)"),
)


def init_schema(conn) -> None:
    """Create every base table (idempotent — ``IF NOT EXISTS`` everywhere)."""
    for _name, ddl in NODE_TABLES:
        conn.execute(ddl)
    for _name, ddl in REL_TABLES:
        conn.execute(ddl)


def expected_table_names() -> Iterable[str]:
    yield from (n for n, _ in NODE_TABLES)
    yield from (n for n, _ in REL_TABLES)


__all__ = ["init_schema", "NODE_TABLES", "REL_TABLES", "expected_table_names"]
