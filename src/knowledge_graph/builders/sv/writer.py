"""Graph-dict → Kuzu writer for the SV builder.

The :func:`write_graph` function takes the in-memory dict produced by
:func:`knowledge_graph.builders.sv.build.build_kg` and materializes it in a
Kuzu store opened via :class:`knowledge_graph.store.KGStore`.

Two-layer category rule (per Phase C plan):

* ``semantic``   — ``node.get("queryable")`` is True.
* ``token``      — ``node.get("is_token")`` is True.
* ``structural`` — anything else.
* ``unresolved`` — Phase C.5 placeholder synthesized for ``_unresolved.*``
  edge endpoints not present in the in-memory ``graph['nodes']``.

Edge mapping mirrors the table set in ``store/schema.py``. Every node also
gets an ``IN_ORIGIN`` edge to its origin row.

Idempotency: every write uses ``MERGE`` on the primary key — re-running the
writer against an unchanged graph produces zero row deltas. For edge types
where ``(src, dst)`` legitimately repeats with distinct payload (e.g.
``imports``, ``imports_item``), the payload key columns participate in the
MERGE pattern so each combination is a separate row.

Origin mapping: SV node ids are namespaced by file-path stem (see
``build.py``). The writer requires a ``origins: dict[str, OriginRef]`` map
keyed by *id prefix* (the part before the first ``:`` in the node id) so it
can attach each node to the correct ``:Origin``. :func:`build_and_store`
constructs this map for the standard multi-file path.

Edges whose endpoints reference unknown node ids are skipped with a
diagnostic counter in the returned :class:`WriteStats`; node-only writes are
unaffected. This matches the plan's "fail loudly or buffer-and-resolve"
contract — we choose *skip with stats* since Kuzu rel tables would otherwise
raise on the missing FK and abort the whole batch.
"""

from __future__ import annotations

import csv
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from knowledge_graph.schemas import OriginRef


# v1.5-#2: row-count threshold above which write_graph switches from the
# per-row Cypher MERGE loop to a Kuzu ``COPY FROM`` bulk path. Justified
# by a micro-bench on this box (see ``tests/.../test_writer_perf.py``):
# baseline per-row cost is ~10 ms/row across N=10/100/1000; the bulk path
# pays a fixed CSV-serialise + flush + COPY-parse cost that only amortises
# above ~100 rows. Below the threshold the per-row loop wins on overhead.
_BULK_COPY_MIN_ROWS: int = 100

# Node-PK chunk size for the pre-COPY DETACH DELETE. Kuzu accepts list
# parameters, but very large lists slow the IN-list scan; 1000 keeps the
# delete latency negligible for realistic batches (~10k nodes/file).
_DELETE_CHUNK: int = 1000


# Map from graph-dict edge ``type`` → (rel table name, payload-extractor).
# The extractor returns the dict of REL-table column values that aren't
# (src, dst). ``None`` means no extra columns.
def _edge_payload_index(e: dict[str, Any]) -> dict[str, Any]:
    return {"ordinal": int(e.get("payload", {}).get("index", 0))}


def _edge_payload_sensitive(e: dict[str, Any]) -> dict[str, Any]:
    return {"edge": str(e.get("payload", {}).get("edge", ""))}


def _edge_payload_connects(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "instance": str(p.get("instance", "") or ""),
        "port": str(p.get("port", "") or ""),
    }


def _edge_payload_param_override(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "name": str(p.get("name", "") or ""),
        "value": str(p.get("value", "") or ""),
    }


def _edge_payload_enum_value(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "name": str(p.get("name", "") or ""),
        "typedef": str(p.get("typedef", "") or ""),
    }


# Phase C.5 payload extractors --------------------------------------------


def _payload_extends(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    params = p.get("params")
    return {
        "name": str(p.get("name", "") or ""),
        "params": (
            "" if params is None
            else params if isinstance(params, str)
            else json.dumps(params, ensure_ascii=False, sort_keys=True)
        ),
    }


def _payload_name_only(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {"name": str(p.get("name", "") or "")}


def _payload_references_interface(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {"modport": str(p.get("modport", "") or "")}


def _payload_dpi_exports(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "spec": str(p.get("spec", "") or ""),
        "export_kind": str(p.get("export_kind", "") or ""),
        "unresolved": bool(p.get("unresolved", False)),
    }


def _payload_imports(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "package": str(p.get("package", "") or ""),
        "item": str(p.get("item", "") or ""),
        "unresolved": bool(p.get("unresolved", False)),
    }


def _payload_imports_item(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "package": str(p.get("package", "") or ""),
        "symbol": str(p.get("symbol", "") or ""),
    }


def _payload_exports_all(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {"wildcard": bool(p.get("wildcard", False))}


def _payload_declares(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "name": str(p.get("name", "") or ""),
        "kind": str(p.get("kind", "") or ""),
    }


def _payload_bind_target(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "target": str(p.get("target", "") or ""),
        "target_module": str(p.get("target_module", "") or ""),
        "ordinal": int(p.get("index", 0) or 0),
        "unresolved": bool(p.get("unresolved", False)),
    }


def _payload_bound_into(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "instance_name": str(p.get("instance_name", "") or ""),
        "scope": str(p.get("scope", "") or ""),
    }


def _payload_defparam_override(e: dict[str, Any]) -> dict[str, Any]:
    p = e.get("payload", {}) or {}
    return {
        "hier_path": str(p.get("hier_path", "") or ""),
        "value": str(p.get("value", "") or ""),
        "unresolved": bool(p.get("unresolved", False)),
    }


EDGE_TABLE_MAP: dict[str, tuple[str, Any]] = {
    "child":           ("PARENT_OF",      _edge_payload_index),
    "drives":          ("DRIVES",         None),
    "reads":           ("READS",          None),
    "sensitive_to":    ("SENSITIVE_TO",   _edge_payload_sensitive),
    "instantiates":    ("INSTANTIATES",   None),
    "of_module":       ("OF_MODULE",      None),
    "connects":        ("CONNECTS",       _edge_payload_connects),
    "param_override":  ("PARAM_OVERRIDE", _edge_payload_param_override),
    "has_port":        ("HAS_PORT",       None),
    "has_param":       ("HAS_PARAM",      None),
    "has_net":         ("HAS_NET",        None),
    "has_typedef":     ("HAS_TYPEDEF",    None),
    "has_enum_value":  ("HAS_ENUM_VALUE", _edge_payload_enum_value),
    "has_modport":     ("HAS_MODPORT",    None),
    "has_function":    ("HAS_FUNCTION",   None),
    "has_generate":    ("HAS_GENERATE",   None),
    "contains_block":  ("CONTAINS_BLOCK", None),
    "calls":           ("CALLS",          None),

    # ---- Phase C.5 additions (auto-derived from SV semantic emit) ----------
    "extends":                  ("EXTENDS",             _payload_extends),
    "implements":               ("IMPLEMENTS",          _payload_name_only),
    "has_class":                ("HAS_CLASS",           None),
    "has_class_property":       ("HAS_CLASS_PROPERTY",  None),
    "has_method":               ("HAS_METHOD",          None),
    "has_constraint":           ("HAS_CONSTRAINT",      None),
    "has_inline_constraint":    ("HAS_INLINE_CONSTRAINT", None),
    "has_type_param":           ("HAS_TYPE_PARAM",      None),
    "has_local_var":            ("HAS_LOCAL_VAR",       None),
    "has_function_port":        ("HAS_FUNCTION_PORT",   None),
    "has_member":               ("HAS_MEMBER",          None),
    "prototypes":               ("PROTOTYPES",          None),
    "has_checker_instance":     ("HAS_CHECKER_INSTANCE", None),
    "has_checker_data":         ("HAS_CHECKER_DATA",    None),
    "of_checker":               ("OF_CHECKER",          _payload_name_only),
    "has_assertion":            ("HAS_ASSERTION",       None),
    "has_assertion_item_port":  ("HAS_ASSERTION_ITEM_PORT", None),
    "has_property":             ("HAS_PROPERTY",        None),
    "has_sequence":             ("HAS_SEQUENCE",        None),
    "has_let":                  ("HAS_LET",             None),
    "has_default_disable":      ("HAS_DEFAULT_DISABLE", None),
    "has_clocking":             ("HAS_CLOCKING",        None),
    "has_clocking_item":        ("HAS_CLOCKING_ITEM",   None),
    "default_clocking":         ("DEFAULT_CLOCKING",    _payload_name_only),
    "references_interface":     ("REFERENCES_INTERFACE", _payload_references_interface),
    "has_covergroup":           ("HAS_COVERGROUP",      None),
    "has_coverpoint":           ("HAS_COVERPOINT",      None),
    "has_bins":                 ("HAS_BINS",            None),
    "has_cross":                ("HAS_CROSS",           None),
    "has_dpi_import":           ("HAS_DPI_IMPORT",      None),
    "dpi_exports":              ("DPI_EXPORTS",         _payload_dpi_exports),
    "imports":                  ("IMPORTS",             _payload_imports),
    "imports_item":             ("IMPORTS_ITEM",        _payload_imports_item),
    "exports_all":              ("EXPORTS_ALL",         _payload_exports_all),
    "declares":                 ("DECLARES",            _payload_declares),
    "bind_target":              ("BIND_TARGET",         _payload_bind_target),
    "bound_into":               ("BOUND_INTO",          _payload_bound_into),
    "defparam_override":        ("DEFPARAM_OVERRIDE",   _payload_defparam_override),
    "has_net_decl":             ("HAS_NET_DECL",        None),
    "has_nettype":              ("HAS_NETTYPE",         None),
    "has_user_defined_net_decl": ("HAS_USER_DEFINED_NET_DECL", None),
    "aliases":                  ("ALIASES",             None),
    "groups_net":               ("GROUPS_NET",          None),
    "groups_port_ref":          ("GROUPS_PORT_REF",     None),
    "has_primitive_instance":   ("HAS_PRIMITIVE_INSTANCE", None),
    "has_procedural_assign":    ("HAS_PROCEDURAL_ASSIGN", None),
    "has_procedural_force":     ("HAS_PROCEDURAL_FORCE", None),
    "has_event_trigger":        ("HAS_EVENT_TRIGGER",   None),
    "triggers":                 ("TRIGGERS",            None),
    "has_genvar":               ("HAS_GENVAR",          None),
    "has_timeunits":            ("HAS_TIMEUNITS",       None),
}


# Edge types where (src,dst) can repeat with distinct payload — listed
# columns become MERGE pattern keys to prevent collapse on re-write.
_MERGE_KEY_OVERRIDES: dict[str, tuple[str, ...]] = {
    "imports":      ("package", "item"),
    "imports_item": ("package", "symbol"),
}


@dataclass
class WriteStats:
    """Diagnostic counters returned by :func:`write_graph`."""

    nodes_written: int = 0
    placeholders_written: int = 0
    in_origin_written: int = 0
    edges_written: dict[str, int] = field(default_factory=dict)
    edges_skipped_missing_endpoint: int = 0
    edges_skipped_unknown_type: dict[str, int] = field(default_factory=dict)

    @property
    def unmapped_edge_type_counts(self) -> dict[str, int]:
        """Phase C.5 API alias for :attr:`edges_skipped_unknown_type`."""
        return self.edges_skipped_unknown_type


def _category_for(node: dict[str, Any]) -> str:
    if node.get("queryable"):
        return "semantic"
    if node.get("is_token"):
        return "token"
    return "structural"


def _prefix_of(node_id: str) -> str:
    """Return the id-prefix used by :func:`build_kg` for namespacing.

    Node ids look like ``<prefix>:n0001.<Class>``; the prefix is the file
    stem (with a numeric suffix for stem collisions). For ungrafted ids
    (no colon) the empty string is returned — callers must handle that
    case if they care.
    """
    idx = node_id.find(":")
    return node_id[:idx] if idx >= 0 else ""


def _serialize_payload(node: dict[str, Any]) -> str:
    """Lossless JSON payload — everything not promoted to a column.

    Includes the structural ``type``, the original ``payload`` dict, plus
    ``semantic`` and ``queryable`` flags when present. The ``span``, ``id``,
    ``kind``, ``is_token`` keys are intentionally excluded — they're either
    promoted to columns or derivable.
    """
    out: dict[str, Any] = {
        "type": node.get("type"),
        "payload": node.get("payload", {}),
    }
    if "semantic" in node:
        out["semantic"] = node["semantic"]
    if node.get("queryable"):
        out["queryable"] = True
    return json.dumps(out, ensure_ascii=False, sort_keys=True, default=str)


def _node_params(
    node: dict[str, Any],
    *,
    source: str,
    corpus: str,
    origin_id: str,
) -> dict[str, Any]:
    span = node.get("span") or {}
    name = None
    sem = node.get("semantic")
    if isinstance(sem, dict):
        n = sem.get("name")
        if isinstance(n, str):
            name = n
    return {
        "id": node["id"],
        "kind": str(node.get("kind", "")),
        "category": _category_for(node),
        "name": name,
        "source": source,
        "corpus": corpus,
        "origin_id": origin_id,
        "start_offset": int(span.get("start_offset", -1)) if span else -1,
        "end_offset": int(span.get("end_offset", -1)) if span else -1,
        "start_line": int(span.get("start_line", 0) or 0) if span else 0,
        "end_line": int(span.get("end_line", 0) or 0) if span else 0,
        "start_col": int(span.get("start_col", 0) or 0) if span else 0,
        "end_col": int(span.get("end_col", 0) or 0) if span else 0,
        "payload": _serialize_payload(node),
    }


_NODE_MERGE_CYPHER = """
MERGE (n:Node {id: $id})
SET n.kind = $kind,
    n.category = $category,
    n.name = $name,
    n.source = $source,
    n.corpus = $corpus,
    n.origin_id = $origin_id,
    n.start_offset = $start_offset,
    n.end_offset = $end_offset,
    n.start_line = $start_line,
    n.end_line = $end_line,
    n.start_col = $start_col,
    n.end_col = $end_col,
    n.payload = $payload
"""


_IN_ORIGIN_MERGE_CYPHER = """
MATCH (n:Node {id: $nid}), (o:Origin {id: $oid})
MERGE (n)-[:IN_ORIGIN]->(o)
"""


def _rel_cypher(
    table: str,
    extra_cols: Iterable[str],
    merge_keys: Iterable[str] = (),
) -> str:
    """Build a MERGE Cypher for a typed rel.

    ``extra_cols`` are payload columns to SET. ``merge_keys`` is the
    subset of those columns that must appear in the relationship pattern
    so multiple distinct edges between the same ``(src, dst)`` pair don't
    collapse on MERGE — e.g. ``IMPORTS`` where one module imports several
    symbols from the same package.
    """
    extra_list = list(extra_cols)
    merge_list = [k for k in merge_keys if k in extra_list]
    rel_pattern = f"r:{table}"
    if merge_list:
        kvs = ", ".join(f"{k}: ${k}" for k in merge_list)
        rel_pattern = f"{rel_pattern} {{{kvs}}}"
    set_cols = [c for c in extra_list if c not in merge_list]
    sets = ", ".join(f"r.{c} = ${c}" for c in set_cols)
    set_clause = f"\nON CREATE SET {sets}\nON MATCH SET {sets}" if sets else ""
    return (
        f"MATCH (a:Node {{id: $src}}), (b:Node {{id: $dst}})\n"
        f"MERGE (a)-[{rel_pattern}]->(b)"
        f"{set_clause}"
    )


def _resolve_origins_for_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    origins: dict[str, OriginRef],
    order: list[str],
) -> dict[str, OriginRef]:
    """Map every node id → OriginRef.

    Strategy:

    1. If the node's id-prefix is in ``origins``, use that.
    2. Otherwise propagate from any inbound edge (typically a ``has_*`` edge
       from a structural parent whose prefix *is* mapped). Iterate to a
       fixed point so chains of synthetic nodes resolve too.
    3. Any still-unresolved node falls back to the origin of the first root
       in ``graph["order"]`` — guarantees ``IN_ORIGIN`` is never null.

    The brief flags this case explicitly: semantic blobs like
    ``checker_data:c_mutex.r_dir`` are not lifted from any single file's
    parse but are owned by a structural declaration in one file.
    """
    by_id_prefix = {n["id"]: _prefix_of(n["id"]) for n in nodes}
    resolved: dict[str, OriginRef] = {}
    unresolved: list[str] = []
    for nid, prefix in by_id_prefix.items():
        ref = origins.get(prefix)
        if ref is not None:
            resolved[nid] = ref
        else:
            unresolved.append(nid)

    if unresolved:
        # Build reverse adjacency once: dst -> list of srcs.
        in_edges: dict[str, list[str]] = {}
        for e in edges:
            in_edges.setdefault(e["dst"], []).append(e["src"])

        progress = True
        while progress and unresolved:
            progress = False
            still: list[str] = []
            for nid in unresolved:
                ref = None
                for src in in_edges.get(nid, []):
                    if src in resolved:
                        ref = resolved[src]
                        break
                if ref is not None:
                    resolved[nid] = ref
                    progress = True
                else:
                    still.append(nid)
            unresolved = still

    if unresolved:
        # Final fallback: first file's origin.
        fallback: OriginRef | None = None
        for root in order:
            ref = origins.get(_prefix_of(root))
            if ref is not None:
                fallback = ref
                break
        if fallback is None and origins:
            fallback = next(iter(origins.values()))
        if fallback is None:
            raise KeyError("no origins provided and no fallback available")
        for nid in unresolved:
            resolved[nid] = fallback

    return resolved


_NODE_CSV_COLUMNS: tuple[str, ...] = (
    "id", "kind", "category", "name", "source", "corpus", "origin_id",
    "start_offset", "end_offset", "start_line", "end_line",
    "start_col", "end_col", "payload",
)


def _node_row_for_csv(params: dict[str, Any]) -> list[Any]:
    """Project a :func:`_node_params` dict to a CSV row matching the
    :data:`_NODE_CSV_COLUMNS` order. ``None`` is emitted as the empty
    string -- Kuzu COPY treats unquoted empties as NULL for nullable
    columns (``name`` is nullable; the other STRING columns are written
    as concrete values upstream so the empty-as-NULL ambiguity does not
    bite)."""
    return [params[c] if params[c] is not None else "" for c in _NODE_CSV_COLUMNS]


def _detach_delete_node_ids(conn: Any, ids: list[str]) -> None:
    """DETACH DELETE the given Node IDs in chunks.

    Run before the bulk COPY so the replacement-merge contract is
    preserved without violating the COPY uniqueness constraint. DETACH
    also wipes every incident REL row, which is what we want -- the
    follow-up COPY of the typed REL tables replays them fresh.
    """
    if not ids:
        return
    for i in range(0, len(ids), _DELETE_CHUNK):
        chunk = ids[i:i + _DELETE_CHUNK]
        conn.execute(
            "MATCH (n:Node) WHERE n.id IN $ids DETACH DELETE n",
            {"ids": chunk},
        )


def _copy_csv(conn: Any, table: str, header: tuple[str, ...],
              rows: list[list[Any]], tmpdir: Path) -> None:
    """Write ``rows`` to a CSV under ``tmpdir`` and ``COPY <table> FROM`` it.

    Empty ``rows`` is a no-op (COPY of zero records is wasted I/O and
    Kuzu's parser still pays for it). The CSV writes the header row so
    we can pass ``header=true`` to Kuzu and stay column-order-agnostic
    on the writer side -- Kuzu still requires the column NAMES to match
    the table schema."""
    if not rows:
        return
    # Distinct file per call so concurrent REL COPYs (sequential here,
    # but the per-table loop reuses tmpdir) don't collide.
    fd, path = tempfile.mkstemp(prefix=f"copy_{table}_", suffix=".csv", dir=tmpdir)
    try:
        with open(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        # Escape backslashes in the path for the Cypher literal (Windows
        # paths would otherwise break; harmless on POSIX).
        path_lit = path.replace("\\", "\\\\")
        conn.execute(f"COPY {table} FROM '{path_lit}' (header=true)")
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass


def _write_graph_bulk(
    conn: Any,
    stats: WriteStats,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    order: list[str],
    origins: dict[str, OriginRef],
    node_origin: dict[str, OriginRef],
    *,
    source: str,
    corpus: str,
) -> WriteStats:
    """Bulk-COPY equivalent of the per-row path in :func:`write_graph`.

    Strategy (replacement-merge preserved by pre-delete):

    1. Resolve placeholder ``_unresolved.*`` endpoints (same logic as
       the per-row path).
    2. ``DETACH DELETE`` every Node ID we are about to write -- removes
       stale row content AND every incident REL row (so the REL COPY
       below replays a clean slice).
    3. ``COPY Node FROM`` one CSV for all real + placeholder nodes.
    4. ``COPY IN_ORIGIN FROM`` one CSV for the (node_id, origin_id)
       pairs.
    5. For each typed REL table that appears in ``edges``, ``COPY <table>
       FROM`` one CSV; payload columns come from the per-edge extractor.

    Edges to unknown endpoints (and edges with unmapped types) are
    counted on ``stats`` and dropped, matching the per-row contract.
    """
    known_ids: set[str] = {n["id"] for n in nodes}

    # --- placeholder synthesis (same rules as the per-row branch) -----
    fallback_origin: OriginRef | None = None
    for root in order:
        ref = origins.get(_prefix_of(root))
        if ref is not None:
            fallback_origin = ref
            break
    if fallback_origin is None and origins:
        fallback_origin = next(iter(origins.values()))

    placeholder_origins: dict[str, OriginRef] = {}
    for edge in edges:
        for endpoint in (edge.get("src"), edge.get("dst")):
            if (
                isinstance(endpoint, str)
                and endpoint.startswith("_unresolved.")
                and endpoint not in known_ids
                and endpoint not in placeholder_origins
            ):
                src_id, dst_id = edge.get("src"), edge.get("dst")
                other = dst_id if endpoint == src_id else src_id
                inherit = (
                    node_origin.get(other) if isinstance(other, str) else None
                )
                origin = inherit or fallback_origin
                if origin is None:
                    continue
                placeholder_origins[endpoint] = origin

    for pid, origin in placeholder_origins.items():
        node_origin[pid] = origin
        known_ids.add(pid)

    # --- build CSV rows -----------------------------------------------
    node_rows: list[list[Any]] = []
    in_origin_rows: list[list[Any]] = []

    for node in nodes:
        nid = node["id"]
        origin = node_origin[nid]
        params = _node_params(
            node, source=source, corpus=corpus, origin_id=origin.id
        )
        node_rows.append(_node_row_for_csv(params))
        in_origin_rows.append([nid, origin.id])
        stats.nodes_written += 1

    for pid, origin in placeholder_origins.items():
        placeholder_name = pid[len("_unresolved."):]
        params = {
            "id": pid, "kind": "Unresolved", "category": "unresolved",
            "name": placeholder_name, "source": source, "corpus": corpus,
            "origin_id": origin.id,
            "start_offset": -1, "end_offset": -1,
            "start_line": 0, "end_line": 0,
            "start_col": 0, "end_col": 0,
            "payload": json.dumps(
                {"type": "Unresolved", "placeholder": True}, sort_keys=True
            ),
        }
        node_rows.append(_node_row_for_csv(params))
        in_origin_rows.append([pid, origin.id])
        stats.placeholders_written += 1
        stats.in_origin_written += 1

    stats.in_origin_written += len(nodes)  # one IN_ORIGIN per real node

    # Bucket typed edges by REL table.
    rel_buckets: dict[str, dict[str, Any]] = {}  # table -> {cols, rows}
    for edge in edges:
        etype = edge.get("type")
        mapping = EDGE_TABLE_MAP.get(etype)
        if mapping is None:
            stats.edges_skipped_unknown_type[etype] = (
                stats.edges_skipped_unknown_type.get(etype, 0) + 1
            )
            continue
        table, extractor = mapping
        src = edge.get("src")
        dst = edge.get("dst")
        if src not in known_ids or dst not in known_ids:
            stats.edges_skipped_missing_endpoint += 1
            continue
        extra: dict[str, Any] = {}
        if extractor is not None:
            extra = extractor(edge)
        bucket = rel_buckets.get(table)
        if bucket is None:
            cols = ("from", "to", *extra.keys())
            bucket = {"cols": cols, "extra_keys": tuple(extra.keys()), "rows": []}
            rel_buckets[table] = bucket
        # Project to the bucket's column order (first edge for the table
        # locks the column set; payload-extractor outputs are stable).
        row = [src, dst, *(extra[k] for k in bucket["extra_keys"])]
        bucket["rows"].append(row)
        stats.edges_written[table] = stats.edges_written.get(table, 0) + 1

    # --- execute deletes + copies -------------------------------------
    # DETACH DELETE clears old rows AND incident rels, so the REL COPYs
    # below land into an empty slice for this batch of IDs.
    all_node_ids = [n["id"] for n in nodes] + list(placeholder_origins.keys())
    _detach_delete_node_ids(conn, all_node_ids)

    # CSVs live in a fresh tmpdir that's removed on success. Kept under
    # the OS temp root rather than the store dir so a partial failure
    # never leaves stray files inside the Kuzu database directory.
    with tempfile.TemporaryDirectory(prefix="kgweave_copy_") as td:
        tmpdir = Path(td)
        _copy_csv(conn, "Node", _NODE_CSV_COLUMNS, node_rows, tmpdir)
        _copy_csv(conn, "IN_ORIGIN", ("from", "to"), in_origin_rows, tmpdir)
        for table, bucket in rel_buckets.items():
            _copy_csv(conn, table, bucket["cols"], bucket["rows"], tmpdir)

    return stats


def write_graph(
    store: Any,
    graph: dict[str, Any],
    *,
    source: str = "sv",
    corpus: str,
    origins: dict[str, OriginRef],
) -> WriteStats:
    """Materialize ``graph`` into ``store`` (a :class:`KGStore`).

    ``origins`` maps the SV id-prefix (file stem with optional collision
    suffix) to the :class:`OriginRef` for that file. Nodes whose prefix is
    not in the map are routed via their structural parent (see
    :func:`_resolve_origins_for_nodes`).

    Returns a :class:`WriteStats` with per-table counts.
    """
    stats = WriteStats()
    conn = store.conn

    nodes: list[dict[str, Any]] = graph.get("nodes", [])
    edges: list[dict[str, Any]] = graph.get("edges", [])
    order: list[str] = graph.get("order", []) or []

    node_origin = _resolve_origins_for_nodes(nodes, edges, origins, order)

    # v1.5-#2: above the threshold, dispatch to the bulk-COPY path.
    # Below it, the per-row INSERT loop wins on overhead (CSV serialise +
    # flush + COPY parse cost doesn't amortise on tiny batches).
    if len(nodes) + len(edges) >= _BULK_COPY_MIN_ROWS:
        return _write_graph_bulk(
            conn, stats, nodes, edges, order, origins, node_origin,
            source=source, corpus=corpus,
        )

    known_ids: set[str] = set()

    # --- nodes -------------------------------------------------------------
    for node in nodes:
        nid = node["id"]
        origin = node_origin[nid]
        params = _node_params(node, source=source, corpus=corpus, origin_id=origin.id)
        conn.execute(_NODE_MERGE_CYPHER, params)
        stats.nodes_written += 1
        known_ids.add(nid)

    # --- materialize ``_unresolved.*`` placeholder endpoints ---------------
    # Phase C.5: semantic rules emit edges whose endpoint is a synthetic
    # ``_unresolved.<name>`` id not present in ``graph['nodes']``. To keep
    # the edge graph-traversable (the lossless mandate), we materialize
    # those endpoints as ``category='unresolved'`` Node rows attached to
    # the same origin as one referenced endpoint (or a fallback). They are
    # excluded from the dict-parity test via the category filter.
    fallback_origin: OriginRef | None = None
    for root in order:
        ref = origins.get(_prefix_of(root))
        if ref is not None:
            fallback_origin = ref
            break
    if fallback_origin is None and origins:
        fallback_origin = next(iter(origins.values()))

    placeholder_origins: dict[str, OriginRef] = {}
    for edge in edges:
        for endpoint in (edge.get("src"), edge.get("dst")):
            if (
                isinstance(endpoint, str)
                and endpoint.startswith("_unresolved.")
                and endpoint not in known_ids
                and endpoint not in placeholder_origins
            ):
                src_id, dst_id = edge.get("src"), edge.get("dst")
                other = dst_id if endpoint == src_id else src_id
                inherit = (
                    node_origin.get(other) if isinstance(other, str) else None
                )
                origin = inherit or fallback_origin
                if origin is None:
                    continue
                placeholder_origins[endpoint] = origin

    for placeholder_id, origin in placeholder_origins.items():
        placeholder_name = placeholder_id[len("_unresolved."):]
        conn.execute(
            _NODE_MERGE_CYPHER,
            {
                "id": placeholder_id,
                "kind": "Unresolved",
                "category": "unresolved",
                "name": placeholder_name,
                "source": source,
                "corpus": corpus,
                "origin_id": origin.id,
                "start_offset": -1,
                "end_offset": -1,
                "start_line": 0,
                "end_line": 0,
                "start_col": 0,
                "end_col": 0,
                "payload": json.dumps(
                    {"type": "Unresolved", "placeholder": True},
                    sort_keys=True,
                ),
            },
        )
        node_origin[placeholder_id] = origin
        known_ids.add(placeholder_id)
        conn.execute(
            _IN_ORIGIN_MERGE_CYPHER, {"nid": placeholder_id, "oid": origin.id}
        )
        stats.placeholders_written += 1
        stats.in_origin_written += 1

    # --- IN_ORIGIN edges ---------------------------------------------------
    for node in nodes:
        nid = node["id"]
        origin = node_origin[nid]
        conn.execute(_IN_ORIGIN_MERGE_CYPHER, {"nid": nid, "oid": origin.id})
        stats.in_origin_written += 1

    # --- typed edges -------------------------------------------------------
    for edge in edges:
        etype = edge.get("type")
        mapping = EDGE_TABLE_MAP.get(etype)
        if mapping is None:
            stats.edges_skipped_unknown_type[etype] = (
                stats.edges_skipped_unknown_type.get(etype, 0) + 1
            )
            continue
        table, extractor = mapping
        src = edge.get("src")
        dst = edge.get("dst")
        if src not in known_ids or dst not in known_ids:
            stats.edges_skipped_missing_endpoint += 1
            continue
        params: dict[str, Any] = {"src": src, "dst": dst}
        extra_cols: tuple[str, ...] = ()
        if extractor is not None:
            extra = extractor(edge)
            params.update(extra)
            extra_cols = tuple(extra.keys())
        merge_keys = _MERGE_KEY_OVERRIDES.get(etype, ())
        conn.execute(_rel_cypher(table, extra_cols, merge_keys), params)
        stats.edges_written[table] = stats.edges_written.get(table, 0) + 1

    return stats


# --------------------------------------------------------------------------
# Full-pipeline convenience entry point used by Phase F's facade.
# --------------------------------------------------------------------------


def _prefix_for_path(path: Path, seen: dict[str, int]) -> str:
    """Reproduce :func:`build_kg`'s stem-collision prefix scheme."""
    stem = path.stem or f"file{len(seen)}"
    n = seen.get(stem, 0)
    seen[stem] = n + 1
    return stem if n == 0 else f"{stem}{n}"


def build_and_store(
    store: Any,
    sv_paths: list[Path] | list[str],
    *,
    source: str = "sv",
    corpus: str,
    lang: str = "systemverilog",
) -> tuple[dict[str, Any], dict[str, OriginRef], WriteStats]:
    """Snapshot → build_kg → write_graph in one shot.

    Returns ``(graph, origins_by_prefix, stats)`` so callers can introspect
    the in-memory build and the persisted-row counts.
    """
    from .build import build_kg  # avoid circular import at module load

    paths = [Path(p) for p in sv_paths]

    # 1. Snapshot each file (idempotent on (uri, sha256)).
    seen: dict[str, int] = {}
    origins_by_prefix: dict[str, OriginRef] = {}
    for p in paths:
        prefix = _prefix_for_path(p, seen)
        ref = store.snapshot_file(p, source=source, corpus=corpus, lang=lang)
        origins_by_prefix[prefix] = ref

    # 2. Build the in-memory graph (uses the same stem-prefix scheme).
    graph, _trees, _comp = build_kg(paths)

    # 3. Materialize.
    stats = write_graph(
        store, graph, source=source, corpus=corpus, origins=origins_by_prefix
    )
    return graph, origins_by_prefix, stats


# --------------------------------------------------------------------------
# Phase E: incremental extract with scoped replacement.
# --------------------------------------------------------------------------


@dataclass
class ExtractStats:
    """Diagnostic summary of an :func:`extract` call.

    ``touched_paths`` = files whose content changed (or are new) — their
    origin subtree was deleted (if present) and re-written.
    ``unchanged_paths`` = files whose sha256 already matched a live origin
    — skipped entirely on the write side.
    ``deleted_paths`` = files swept under ``prune=True`` (origin existed for
    ``(source, corpus)`` but path was not in this call).
    """

    touched_paths: list[str] = field(default_factory=list)
    unchanged_paths: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)
    write_stats: WriteStats | None = None
    gc_pruned: int = 0


def _sha_of(path: Path) -> str:
    from knowledge_graph.shared.ids import sha256_bytes
    return sha256_bytes(path.read_bytes())


def extract(
    store: Any,
    sv_paths: list[Path] | list[str],
    *,
    source: str = "sv",
    corpus: str,
    lang: str = "systemverilog",
    prune: bool = False,
    gc: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, OriginRef], ExtractStats]:
    """Incremental SV extract with replacement semantics.

    For each input path:

    * If a current ``:Origin`` exists for ``(uri, source, corpus)`` with a
      DIFFERENT sha256 — that origin's subtree (origin + nodes + all rels
      touching those nodes) is **deleted**; the new content is snapshotted.
    * If no current origin exists — the file is snapshotted fresh.
    * If a current origin exists with a MATCHING sha — the file is marked
      unchanged and skipped on the write side.

    If ``prune=True``, any current origin for ``(source, corpus)`` whose
    ``uri`` is not in the input set is swept the same way (use for "this is
    now the complete corpus" semantics).

    If ``gc=True``, the call (a) implies ``prune=True`` — the input set is
    the complete corpus and origins outside it within
    ``(source, corpus)`` are swept — and (b) runs
    :meth:`KGStore.prune_orphaned_origins` scoped to ``(source, corpus)``
    once writes complete, dropping any Origin row that ended up without a
    child Node. The double-sweep is cheap on a clean store
    (idempotent — returns 0) and closes the orphan-hygiene gap surfaced
    by JOURNAL v1.2 item #5.

    The Cypher write step only pushes nodes whose origin is in the
    ``touched_paths`` set. Untouched origins, their nodes, and rels between
    them are unaffected.

    Returns ``(graph, origins_by_prefix, ExtractStats)``. ``graph`` is
    ``None`` when nothing changed (no work done).
    """
    from .build import build_kg

    paths = [Path(p) for p in sv_paths]

    stats_e = ExtractStats(write_stats=None)
    seen: dict[str, int] = {}
    new_uris: set[str] = set()
    touched_paths: list[Path] = []
    origins_by_prefix: dict[str, OriginRef] = {}
    touched_origin_ids: set[str] = set()
    prefix_for_path: dict[str, str] = {}

    for p in paths:
        prefix = _prefix_for_path(p, seen)
        prefix_for_path[str(p)] = prefix
        uri = str(p.resolve())
        new_uris.add(uri)
        new_sha = _sha_of(p)
        existing = store.find_current_origin(uri=uri, source=source, corpus=corpus)
        if existing is not None and existing.sha256 == new_sha:
            origins_by_prefix[prefix] = existing
            stats_e.unchanged_paths.append(uri)
            continue
        if existing is not None and existing.sha256 != new_sha:
            store.delete_origin_subtree(existing.id)
        touched_paths.append(p)
        stats_e.touched_paths.append(uri)

    effective_prune = prune or gc
    if effective_prune:
        res = store.conn.execute(
            """
            MATCH (o:Origin)
            WHERE o.source = $source AND o.corpus = $corpus
            RETURN o.id, o.uri
            """,
            {"source": source, "corpus": corpus},
        )
        while res.has_next():
            row = res.get_next()
            oid, uri = row[0], row[1]
            if uri not in new_uris:
                store.delete_origin_subtree(oid)
                stats_e.deleted_paths.append(uri)

    if not touched_paths:
        if gc:
            stats_e.gc_pruned = store.prune_orphaned_origins(
                source=source, corpus=corpus
            )
        return None, origins_by_prefix, stats_e

    for p in touched_paths:
        prefix = prefix_for_path[str(p)]
        ref = store.snapshot_file(p, source=source, corpus=corpus, lang=lang)
        origins_by_prefix[prefix] = ref
        touched_origin_ids.add(ref.id)

    # Whole-corpus build — SV semantic resolution is cross-file.
    graph, _trees, _comp = build_kg(paths)
    filtered = _filter_graph_to_origins(
        graph, origins_by_prefix, touched_origin_ids
    )
    write_stats = write_graph(
        store, filtered, source=source, corpus=corpus, origins=origins_by_prefix
    )
    stats_e.write_stats = write_stats
    if gc:
        stats_e.gc_pruned = store.prune_orphaned_origins(
            source=source, corpus=corpus
        )
    return graph, origins_by_prefix, stats_e


def _filter_graph_to_origins(
    graph: dict[str, Any],
    origins_by_prefix: dict[str, OriginRef],
    touched_origin_ids: set[str],
) -> dict[str, Any]:
    """Subset ``graph`` to nodes whose resolved origin is in ``touched_origin_ids``.

    Uses :func:`_resolve_origins_for_nodes` to determine each node's origin
    (same logic the writer would apply), then drops nodes outside the
    touched set and edges whose endpoints fall outside it.
    """
    nodes: list[dict[str, Any]] = graph.get("nodes", [])
    edges: list[dict[str, Any]] = graph.get("edges", [])
    order: list[str] = graph.get("order", []) or []

    node_origin = _resolve_origins_for_nodes(nodes, edges, origins_by_prefix, order)
    keep_ids = {
        n["id"] for n in nodes if node_origin[n["id"]].id in touched_origin_ids
    }
    kept_nodes = [n for n in nodes if n["id"] in keep_ids]
    # ``_unresolved.<name>`` endpoints are NOT in ``graph['nodes']`` — they're
    # synthesized by the writer's Phase-C.5 placeholder loop when an edge
    # references an unknown id. Treat them as implicitly-present here so the
    # filter doesn't strip the edge BEFORE the writer gets a chance to
    # materialize the placeholder. Without this, every ``imports``,
    # ``dpi_exports``, ``bind_target``, ... edge to an unresolved symbol is
    # silently dropped — a lossless-property regression that masks itself
    # because no exception fires.
    def _endpoint_ok(eid: Any) -> bool:
        return (
            isinstance(eid, str)
            and (eid in keep_ids or eid.startswith("_unresolved."))
        )
    kept_edges = [
        e for e in edges if _endpoint_ok(e.get("src")) and _endpoint_ok(e.get("dst"))
    ]
    kept_order = [oid for oid in order if oid in keep_ids]
    return {"nodes": kept_nodes, "edges": kept_edges, "order": kept_order}


__all__ = [
    "write_graph",
    "build_and_store",
    "extract",
    "WriteStats",
    "ExtractStats",
    "EDGE_TABLE_MAP",
]
