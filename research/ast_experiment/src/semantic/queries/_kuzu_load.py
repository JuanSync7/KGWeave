"""Load the in-memory KG dict into an embedded kuzu graph DB.

This is the semantic-layer projection of the graph into kuzu for Cypher
queries. It mirrors the proven reference loader in
``evals/cypher_ab/kuzu_load.py`` with the following invariants:

* ONE node table ``N`` with columns ``(id, role, name, path, direction)``
  — all promoted (queryable) nodes are rows.
* ONE rel table **per semantic edge type** (reads, drives, of_type, …);
  idiomatic ``-[:reads]->`` Cypher works.
* Structural ``child`` edges are NOT loaded.
* Edges whose target is non-promoted (not in node_ids) or ``_unresolved``
  are skipped — they have no row to point at.
* kuzu Database path MUST be a non-existent subpath of a temp dir:
  ``os.path.join(tempfile.mkdtemp(), "kg")`` — mkdtemp creates the parent;
  kuzu requires the final component to be absent.

NO ``import re`` / ``from re`` in this module.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Tuple


def _ident(edge_type: str) -> bool:
    """Return True if edge_type is a plain identifier (valid kuzu rel-table name)."""
    return edge_type.isidentifier()


def _EDGE_TYPES(graph: dict[str, Any]) -> set[str]:
    """Return the set of semantic edge types that would be loaded for graph.

    Used by tests to verify that 'child' is not in the set.
    """
    nodes = [n for n in graph["nodes"] if n.get("queryable")]
    node_ids = {n["id"] for n in nodes}
    return {
        e["type"]
        for e in graph["edges"]
        if e["type"] != "child"
        and e["src"] in node_ids
        and e["dst"] in node_ids
        and _ident(e["type"])
    }


def _kuzu_load(graph: dict[str, Any]) -> Tuple[Any, str]:
    """Return ``(conn, tmpdir)`` for the semantic projection of ``graph``.

    Returns a 2-tuple:
    - ``conn``: a ``kuzu.Connection`` holding the projection.
    - ``tmpdir``: the path to the temp directory that was created (the parent
      of the kuzu DB path).  The caller is responsible for removing it when
      the connection is no longer needed — use ``shutil.rmtree(tmpdir,
      ignore_errors=True)``.

    kuzu is imported inside this function so that importing this module
    does not require kuzu to be installed.
    """
    import kuzu  # lazy import — do not move to module level

    nodes = [n for n in graph["nodes"] if n.get("queryable")]
    node_ids = {n["id"] for n in nodes}
    edges = [
        e for e in graph["edges"]
        if e["type"] != "child"
        and e["src"] in node_ids
        and e["dst"] in node_ids
        and _ident(e["type"])
    ]
    edge_types = sorted({e["type"] for e in edges})

    tmpdir = tempfile.mkdtemp(prefix="kg_kuzu_")
    db_path = os.path.join(tmpdir, "kg")
    conn = kuzu.Connection(kuzu.Database(db_path))
    conn.execute(
        "CREATE NODE TABLE N(id STRING, role STRING, name STRING, path STRING, "
        "direction STRING, PRIMARY KEY(id))"
    )
    for t in edge_types:
        conn.execute(f"CREATE REL TABLE {t}(FROM N TO N)")

    for n in nodes:
        sem = n.get("semantic", {}) or {}
        attrs = sem.get("attributes", {}) or {}
        conn.execute(
            "CREATE (x:N {id:$id, role:$role, name:$name, path:$path, "
            "direction:$direction})",
            {
                "id": n["id"],
                "role": sem.get("role"),
                "name": sem.get("name"),
                "path": sem.get("path"),
                "direction": attrs.get("direction"),
            },
        )
    for e in edges:
        conn.execute(
            f"MATCH (a:N),(b:N) WHERE a.id=$s AND b.id=$d CREATE (a)-[:{e['type']}]->(b)",
            {"s": e["src"], "d": e["dst"]},
        )
    return conn, tmpdir
