"""Load the in-memory KG dict into an embedded kuzu graph DB so real Cypher
runs against the *same* graph the pattern-dict surface queries.

Why kuzu (not a pure-Python Cypher subset): it's a real Cypher engine with a
real parser/planner, so a model's syntactically-valid Cypher executes for real
reasons — a failure is the model's, not the engine's. That fidelity is the whole
point of the Cypher-vs-pattern-dict accuracy A/B.

Modelling choice (kept faithful to idiomatic Cypher):
  * ONE node table ``N`` with the lifted semantic fields as columns
    (``id`` PK, ``role``, ``name``, ``path``, plus ``direction`` so attribute
    questions are answerable). All promoted nodes are rows.
  * ONE rel table **per semantic edge type** (``reads``, ``drives``, ``of_type``,
    ``has_method`` …) so a model writes idiomatic ``-[:reads]->`` rather than a
    generic ``-[r] WHERE r.type=...``. Structural ``child`` edges are NOT loaded
    (the card never exposes them; both surfaces query the semantic layer only).

Edges whose endpoint is not a promoted node (e.g. ``_unresolved.*`` sentinels)
are skipped — they have no row to point at, exactly as a real query would find.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import kuzu


def _ident(edge_type: str) -> bool:
    """kuzu rel-table names must be plain identifiers; all our semantic edge
    types already are (``has_*``, ``of_type``, … — no dots/spaces)."""
    return edge_type.isidentifier()


def load_kuzu(graph: dict[str, Any]) -> kuzu.Connection:
    """Return a kuzu Connection holding the semantic projection of ``graph``."""
    nodes = [n for n in graph["nodes"] if n.get("queryable")]
    node_ids = {n["id"] for n in nodes}
    edges = [
        e for e in graph["edges"]
        if e["type"] != "child"
        and e["src"] in node_ids and e["dst"] in node_ids
        and _ident(e["type"])
    ]
    edge_types = sorted({e["type"] for e in edges})

    db_path = os.path.join(tempfile.mkdtemp(prefix="kg_kuzu_"), "kg")
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
    return conn


def run_cypher(conn: kuzu.Connection, cypher: str) -> frozenset[str]:
    """Execute Cypher and normalise the result to a set of answer strings.

    One column → the value; multiple columns → joined with ``|`` (so a
    ``RETURN a.path, b.name`` pair-query is gradeable against pipe-joined truth).
    ``None`` cells are dropped from single-column results. Any execution error
    (syntax, unknown property, …) raises — the caller grades that as a miss,
    which is the honest cost of Cypher's error surface vs the pattern-dict's
    can't-malform contract.
    """
    res = conn.execute(cypher)
    out: set[str] = set()
    while res.has_next():
        row = res.get_next()
        if len(row) == 1:
            if row[0] is not None:
                out.add(str(row[0]))
        else:
            out.add("|".join("" if v is None else str(v) for v in row))
    return frozenset(out)
