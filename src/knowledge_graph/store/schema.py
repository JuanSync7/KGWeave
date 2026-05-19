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

# ---------------------------------------------------------------- schema version
#
# Single source of truth for the on-disk schema version. Bump this when the
# DDL or any binary-incompatible invariant changes; ``open_store`` will
# refuse to open a store whose ``:Meta.schema_version`` does not match.
#
# Format: ``"<major>.<minor>.<patch>"`` plain strings — no parsing, just
# equality. Equality is intentional: even patch-level drift means the
# writer was a different code version and should be surfaced rather than
# silently tolerated.
KGWEAVE_SCHEMA_VERSION: str = "1.2.0"


class SchemaVersionMismatch(RuntimeError):
    """Raised by :func:`verify_or_migrate_schema_version` when the on-disk
    ``:Meta.schema_version`` does not match :data:`KGWEAVE_SCHEMA_VERSION`.

    Attributes
    ----------
    stored:
        The version string read from the store, or ``None`` when the
        ``:Meta`` row was absent and migration was disabled.
    expected:
        The version this build of KGWeave expects (i.e. the running value
        of :data:`KGWEAVE_SCHEMA_VERSION`).
    """

    def __init__(self, *, stored: str | None, expected: str) -> None:
        self.stored = stored
        self.expected = expected
        super().__init__(
            f"KGWeave schema version mismatch: stored={stored!r}, expected={expected!r}"
        )


NODE_TABLES: tuple[tuple[str, str], ...] = (
    (
        "Meta",
        """
        CREATE NODE TABLE IF NOT EXISTS Meta (
            singleton_key STRING,
            schema_version STRING,
            PRIMARY KEY (singleton_key)
        )
        """,
    ),
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

    # ---- Phase C.5 auto-derived from SV semantic emit ----------------------
    ("EXTENDS",            "CREATE REL TABLE IF NOT EXISTS EXTENDS (FROM Node TO Node, name STRING, params STRING)"),
    ("IMPLEMENTS",         "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS (FROM Node TO Node, name STRING)"),
    ("HAS_CLASS",          "CREATE REL TABLE IF NOT EXISTS HAS_CLASS (FROM Node TO Node)"),
    ("HAS_CLASS_PROPERTY", "CREATE REL TABLE IF NOT EXISTS HAS_CLASS_PROPERTY (FROM Node TO Node)"),
    ("HAS_METHOD",         "CREATE REL TABLE IF NOT EXISTS HAS_METHOD (FROM Node TO Node)"),
    ("HAS_CONSTRAINT",     "CREATE REL TABLE IF NOT EXISTS HAS_CONSTRAINT (FROM Node TO Node)"),
    ("HAS_INLINE_CONSTRAINT", "CREATE REL TABLE IF NOT EXISTS HAS_INLINE_CONSTRAINT (FROM Node TO Node)"),
    ("HAS_TYPE_PARAM",     "CREATE REL TABLE IF NOT EXISTS HAS_TYPE_PARAM (FROM Node TO Node)"),
    ("HAS_LOCAL_VAR",      "CREATE REL TABLE IF NOT EXISTS HAS_LOCAL_VAR (FROM Node TO Node)"),
    ("HAS_FUNCTION_PORT",  "CREATE REL TABLE IF NOT EXISTS HAS_FUNCTION_PORT (FROM Node TO Node)"),
    ("HAS_MEMBER",         "CREATE REL TABLE IF NOT EXISTS HAS_MEMBER (FROM Node TO Node)"),
    ("PROTOTYPES",         "CREATE REL TABLE IF NOT EXISTS PROTOTYPES (FROM Node TO Node)"),
    ("HAS_CHECKER_INSTANCE", "CREATE REL TABLE IF NOT EXISTS HAS_CHECKER_INSTANCE (FROM Node TO Node)"),
    ("HAS_CHECKER_DATA",   "CREATE REL TABLE IF NOT EXISTS HAS_CHECKER_DATA (FROM Node TO Node)"),
    ("OF_CHECKER",         "CREATE REL TABLE IF NOT EXISTS OF_CHECKER (FROM Node TO Node, name STRING)"),
    ("HAS_ASSERTION",      "CREATE REL TABLE IF NOT EXISTS HAS_ASSERTION (FROM Node TO Node)"),
    ("HAS_ASSERTION_ITEM_PORT", "CREATE REL TABLE IF NOT EXISTS HAS_ASSERTION_ITEM_PORT (FROM Node TO Node)"),
    ("HAS_PROPERTY",       "CREATE REL TABLE IF NOT EXISTS HAS_PROPERTY (FROM Node TO Node)"),
    ("HAS_SEQUENCE",       "CREATE REL TABLE IF NOT EXISTS HAS_SEQUENCE (FROM Node TO Node)"),
    ("HAS_LET",            "CREATE REL TABLE IF NOT EXISTS HAS_LET (FROM Node TO Node)"),
    ("HAS_DEFAULT_DISABLE", "CREATE REL TABLE IF NOT EXISTS HAS_DEFAULT_DISABLE (FROM Node TO Node)"),
    ("HAS_CLOCKING",       "CREATE REL TABLE IF NOT EXISTS HAS_CLOCKING (FROM Node TO Node)"),
    ("HAS_CLOCKING_ITEM",  "CREATE REL TABLE IF NOT EXISTS HAS_CLOCKING_ITEM (FROM Node TO Node)"),
    ("DEFAULT_CLOCKING",   "CREATE REL TABLE IF NOT EXISTS DEFAULT_CLOCKING (FROM Node TO Node, name STRING)"),
    ("REFERENCES_INTERFACE", "CREATE REL TABLE IF NOT EXISTS REFERENCES_INTERFACE (FROM Node TO Node, modport STRING)"),
    ("HAS_COVERGROUP",     "CREATE REL TABLE IF NOT EXISTS HAS_COVERGROUP (FROM Node TO Node)"),
    ("HAS_COVERPOINT",     "CREATE REL TABLE IF NOT EXISTS HAS_COVERPOINT (FROM Node TO Node)"),
    ("HAS_BINS",           "CREATE REL TABLE IF NOT EXISTS HAS_BINS (FROM Node TO Node)"),
    ("HAS_CROSS",          "CREATE REL TABLE IF NOT EXISTS HAS_CROSS (FROM Node TO Node)"),
    ("HAS_DPI_IMPORT",     "CREATE REL TABLE IF NOT EXISTS HAS_DPI_IMPORT (FROM Node TO Node)"),
    ("DPI_EXPORTS",        "CREATE REL TABLE IF NOT EXISTS DPI_EXPORTS (FROM Node TO Node, spec STRING, export_kind STRING, unresolved BOOLEAN)"),
    ("IMPORTS",            "CREATE REL TABLE IF NOT EXISTS IMPORTS (FROM Node TO Node, package STRING, item STRING, unresolved BOOLEAN)"),
    ("IMPORTS_ITEM",       "CREATE REL TABLE IF NOT EXISTS IMPORTS_ITEM (FROM Node TO Node, package STRING, symbol STRING)"),
    ("EXPORTS_ALL",        "CREATE REL TABLE IF NOT EXISTS EXPORTS_ALL (FROM Node TO Node, wildcard BOOLEAN)"),
    ("DECLARES",           "CREATE REL TABLE IF NOT EXISTS DECLARES (FROM Node TO Node, name STRING, kind STRING)"),
    ("BIND_TARGET",        "CREATE REL TABLE IF NOT EXISTS BIND_TARGET (FROM Node TO Node, target STRING, target_module STRING, ordinal INT32, unresolved BOOLEAN)"),
    ("BOUND_INTO",         "CREATE REL TABLE IF NOT EXISTS BOUND_INTO (FROM Node TO Node, instance_name STRING, scope STRING)"),
    ("DEFPARAM_OVERRIDE",  "CREATE REL TABLE IF NOT EXISTS DEFPARAM_OVERRIDE (FROM Node TO Node, hier_path STRING, value STRING, unresolved BOOLEAN)"),
    ("HAS_NET_DECL",       "CREATE REL TABLE IF NOT EXISTS HAS_NET_DECL (FROM Node TO Node)"),
    ("HAS_NETTYPE",        "CREATE REL TABLE IF NOT EXISTS HAS_NETTYPE (FROM Node TO Node)"),
    ("HAS_USER_DEFINED_NET_DECL", "CREATE REL TABLE IF NOT EXISTS HAS_USER_DEFINED_NET_DECL (FROM Node TO Node)"),
    ("ALIASES",            "CREATE REL TABLE IF NOT EXISTS ALIASES (FROM Node TO Node)"),
    ("GROUPS_NET",         "CREATE REL TABLE IF NOT EXISTS GROUPS_NET (FROM Node TO Node)"),
    ("GROUPS_PORT_REF",    "CREATE REL TABLE IF NOT EXISTS GROUPS_PORT_REF (FROM Node TO Node)"),
    ("HAS_PRIMITIVE_INSTANCE", "CREATE REL TABLE IF NOT EXISTS HAS_PRIMITIVE_INSTANCE (FROM Node TO Node)"),
    ("HAS_PROCEDURAL_ASSIGN", "CREATE REL TABLE IF NOT EXISTS HAS_PROCEDURAL_ASSIGN (FROM Node TO Node)"),
    ("HAS_PROCEDURAL_FORCE", "CREATE REL TABLE IF NOT EXISTS HAS_PROCEDURAL_FORCE (FROM Node TO Node)"),
    ("HAS_EVENT_TRIGGER",  "CREATE REL TABLE IF NOT EXISTS HAS_EVENT_TRIGGER (FROM Node TO Node)"),
    ("TRIGGERS",           "CREATE REL TABLE IF NOT EXISTS TRIGGERS (FROM Node TO Node)"),
    ("HAS_GENVAR",         "CREATE REL TABLE IF NOT EXISTS HAS_GENVAR (FROM Node TO Node)"),
    ("HAS_TIMEUNITS",      "CREATE REL TABLE IF NOT EXISTS HAS_TIMEUNITS (FROM Node TO Node)"),
)


def init_schema(conn) -> None:
    """Create every base table (idempotent — ``IF NOT EXISTS`` everywhere)."""
    for _name, ddl in NODE_TABLES:
        conn.execute(ddl)
    for _name, ddl in REL_TABLES:
        conn.execute(ddl)


_META_SINGLETON_KEY: str = "kgweave"


def verify_or_migrate_schema_version(conn) -> str:
    """Reconcile the on-disk ``:Meta.schema_version`` with the running constant.

    Behaviour:

    * **Empty Meta** (fresh store *or* legacy pre-:Meta store): write the
      current :data:`KGWEAVE_SCHEMA_VERSION`. This silently migrates
      legacy stores up — KGWeave is pre-1.0 and forcing re-extracts is
      wasteful.
    * **Existing row, matching version**: no-op.
    * **Existing row, mismatched version**: raise
      :class:`SchemaVersionMismatch`.
    * **Multiple rows** (defensive — should be impossible given the
      singleton PK): take the lexicographically smallest version for the
      comparison and surface mismatch if it doesn't match. Two writers
      cannot both create the row because the primary key
      ``singleton_key`` is fixed to a single value, so the second writer
      will collide; we use ``MERGE`` to make first-open race-safe.

    Returns the resolved on-disk version (always equal to
    :data:`KGWEAVE_SCHEMA_VERSION` on a successful return).
    """
    res = conn.execute(
        "MATCH (m:Meta) RETURN m.schema_version ORDER BY m.schema_version ASC"
    )
    rows: list[str] = []
    while res.has_next():
        rows.append(res.get_next()[0])

    if not rows:
        # Fresh or legacy store: write the current version. MERGE is
        # idempotent against a race where a parallel writer created the
        # same singleton row a moment ago.
        conn.execute(
            "MERGE (m:Meta {singleton_key: $k}) SET m.schema_version = $v",
            {"k": _META_SINGLETON_KEY, "v": KGWEAVE_SCHEMA_VERSION},
        )
        return KGWEAVE_SCHEMA_VERSION

    stored = rows[0]
    if stored != KGWEAVE_SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            stored=stored, expected=KGWEAVE_SCHEMA_VERSION
        )
    return stored


def expected_table_names() -> Iterable[str]:
    yield from (n for n, _ in NODE_TABLES)
    yield from (n for n, _ in REL_TABLES)


__all__ = [
    "init_schema",
    "verify_or_migrate_schema_version",
    "KGWEAVE_SCHEMA_VERSION",
    "SchemaVersionMismatch",
    "NODE_TABLES",
    "REL_TABLES",
    "expected_table_names",
]
