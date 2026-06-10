"""Typed Cypher query runner over the semantic graph.

``cypher_query(graph, query)`` is the public entry point. It lazily builds a
kuzu projection of the graph, executes the query, and returns a typed
``CypherResult``.

kuzu is lazy-imported inside ``cypher_query`` so that importing this module
does NOT require kuzu to be installed.

RESULT CONTRACT — faithful projection + CONDITIONAL hydration:
each cell is whatever the query projected, dispatched on kuzu's returned column
type:

  * scalar projection (``s.name``, ``count(p)``, ``i.path``) → a plain scalar
    (str | int | float | bool | None). Left untouched.
  * node-valued projection (``RETURN s`` — a whole node) → a ``SemanticNode``
    Pydantic model ``(id, role, name, path, attributes)``, HYDRATED BY id from
    ``graph["nodes"]``. The flattened kuzu row LOSES the nested
    ``semantic.attributes`` dict, so we read the node's ``id`` off the kuzu
    return value and rebuild ``SemanticNode`` from that node's ``semantic``
    block.

ERROR CONTRACT — CypherError is raised, never returned:
    On any malformed or schema-violating query, ``cypher_query`` raises a
    ``CypherError`` (imported from ``_cypher_validate``).  The return type is
    always ``CypherResult`` — never a union.  A syntactically valid query with
    zero matches still returns an empty ``CypherResult`` (empty != error).

    ``CypherError`` carries:
        kind       — one of syntax | unknown_label | unknown_edge |
                     unknown_property | engine
        message    — human-readable description (never a raw kuzu traceback)
        suggestion — nearest-match name from the live vocabulary, or None

    Re-exported from this module so consumers can ``from ... import CypherError``
    without knowing about ``_cypher_validate``.

NO ``import re`` / ``from re`` in this module.
"""

from __future__ import annotations

import shutil
from typing import Any

from pydantic import BaseModel

from ._cypher_validate import CypherError, classify_kuzu_error  # re-exported

__all__ = ["CypherResult", "SemanticNode", "CypherError", "cypher_query"]


class SemanticNode(BaseModel):
    """A node-valued Cypher projection (``RETURN s``), hydrated by id.

    Built by looking the node up by its ``id`` in ``graph["nodes"]`` and
    reading its ``semantic`` block — so the nested ``attributes`` dict (which
    the flattened kuzu node row drops) is preserved.

    Attributes:
        id:         The node's stable graph id (kuzu primary key).
        role:       Semantic role (``module``, ``port``, ``class``, …).
        name:       Local name, if any.
        path:       Hierarchical path, if any.
        attributes: The node's nested ``semantic.attributes`` dict.
    """

    id: str
    role: str | None = None
    name: str | None = None
    path: str | None = None
    attributes: dict[str, Any] = {}


def _is_kuzu_node(value: Any) -> bool:
    """True if a kuzu return cell is a whole-node value (vs a scalar).

    kuzu represents ``RETURN s`` as a ``dict`` of the node's properties,
    carrying the internal ``_id`` / ``_label`` keys alongside the ``id``
    primary key. A scalar projection (``s.name``, ``count(p)``) is a plain
    str / int / float / bool / None — never a dict with these markers.
    """
    return (
        isinstance(value, dict)
        and "_id" in value
        and "_label" in value
        and "id" in value
    )


def _hydrate_node(value: dict[str, Any], by_id: dict[str, Any]) -> "SemanticNode":
    """Rebuild a ``SemanticNode`` from a kuzu node cell, by id.

    Reads the node's ``id`` off the kuzu return value, looks it up in
    ``graph["nodes"]`` (``by_id``), and builds the model from that node's
    ``semantic`` block — restoring the nested ``attributes`` dict the flat
    kuzu row dropped. Falls back to the flat row's fields if the id is somehow
    absent (defensive; should not happen for loaded nodes).
    """
    node_id = value["id"]
    node = by_id.get(node_id)
    if node is None:
        return SemanticNode(
            id=node_id,
            role=value.get("role"),
            name=value.get("name"),
            path=value.get("path"),
            attributes={},
        )
    sem = node.get("semantic", {}) or {}
    return SemanticNode(
        id=node_id,
        role=sem.get("role"),
        name=sem.get("name"),
        path=sem.get("path"),
        attributes=sem.get("attributes") or {},
    )


class CypherResult(BaseModel):
    """Typed result of a Cypher query.

    Attributes:
        columns: Ordered list of column names returned by the query.
        rows:    Each row is a dict mapping column name to value.
    """

    columns: list[str]
    rows: list[dict[str, Any]]

    def scalars(self) -> list[Any]:
        """Convenience for single-column results.

        Returns a flat list of values from the sole column, with ``None``
        values dropped.  Raises ``ValueError`` if the result has more than
        one column.
        """
        if len(self.columns) != 1:
            raise ValueError(
                f"scalars() requires exactly 1 column, got {len(self.columns)}: "
                f"{self.columns}"
            )
        col = self.columns[0]
        return [row[col] for row in self.rows if row[col] is not None]


def cypher_query(graph: dict[str, Any], query: str) -> CypherResult:
    """Execute a Cypher query against the semantic projection of ``graph``.

    kuzu is lazy-imported inside this function so that the module can be
    imported without kuzu installed.

    Args:
        graph: The in-memory KG dict produced by ``build_kg``.
        query: A Cypher query string.

    Returns:
        A ``CypherResult`` with ``columns`` and ``rows``.
    """
    from ._kuzu_load import _kuzu_load  # local import to keep kuzu lazy

    # Index for by-id hydration of node-valued projections (RETURN s). The
    # flattened kuzu node row loses the nested semantic.attributes dict, so we
    # rebuild from graph["nodes"] by id.
    by_id = {n["id"]: n for n in graph["nodes"]}

    conn, tmpdir = _kuzu_load(graph)
    try:
        try:
            res = conn.execute(query)
        except Exception as exc:
            # Translate every kuzu exception (RuntimeError, etc.) into a
            # structured CypherError — never let raw kuzu tracebacks escape.
            raise classify_kuzu_error(exc, graph) from None

        # Extract column names from the QueryResult — eagerly consume all rows
        # before we tear down the connection/DB.
        columns: list[str] = res.get_column_names()
        rows: list[dict[str, Any]] = []
        while res.has_next():
            raw_row = res.get_next()
            row: dict[str, Any] = {}
            for col, val in zip(columns, raw_row):
                # CONDITIONAL hydration: node-valued cells → SemanticNode (by
                # id); scalar projections stay scalar.
                row[col] = _hydrate_node(val, by_id) if _is_kuzu_node(val) else val
            rows.append(row)
    finally:
        # The connection and DB are no longer needed once rows are extracted.
        # Remove the temp dir unconditionally so we never accumulate kg_kuzu_*
        # dirs across repeated calls (which would exhaust per-user disk quota).
        shutil.rmtree(tmpdir, ignore_errors=True)

    return CypherResult(columns=columns, rows=rows)
