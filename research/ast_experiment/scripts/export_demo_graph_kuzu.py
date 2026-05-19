"""Export the demo ``graph.json`` exclusively via the public ``knowledge_graph`` facade.

This is the Kuzu-port replacement for :mod:`export_demo_graph`. Instead of
walking ``build_kg``'s in-memory dict, it:

1. Opens (or re-creates) a temp Kuzu store via :func:`knowledge_graph.open_store`.
2. Runs :func:`knowledge_graph.extract` on every ``corpus/*.sv`` file under the
   ``source='sv'``, ``corpus='demo'`` namespace.
3. Reads everything back via :func:`knowledge_graph.cypher` (raw read-only) and
   :func:`knowledge_graph.source_at` to reconstruct the SPEC §3 demo shape:

   * ``files[]`` — one per ``:Origin`` row owned by the demo extract.
   * ``nodes[]`` — projected from ``:Node`` rows; the ``payload`` JSON column is
     re-parsed back into the legacy ``{type, payload, semantic?, queryable?}``
     shape, byte offsets are converted to char offsets for FE consumption.
   * ``edges[]`` — one query per rel table in :data:`EDGE_TABLE_MAP`; the type
     string is the legacy edge-type key (e.g. ``child``, ``has_port``).
   * ``ruleFamilies[]`` — same SPEC §4 rollup as the legacy exporter; the
     ``kind -> ruleId`` table is built from the internal rule modules (these
     are static metadata that doesn't round-trip through the graph).

Allowed differences vs the legacy artifact (documented in JOURNAL v1.2 #3):

* ``generatedAt`` timestamp will differ.
* ``meta.schemaVersion`` (we keep ``version="1"``, but the artifact gains an
  ``exporter`` field naming this script for forensics).
* Edge ids (``e00000`` ..) and node listing order are derived from a stable
  sort over the Kuzu read-back rather than from ``build_kg``'s DFS — the
  ``(src,dst,type)`` SET is preserved (see the structural-diff test).
* Token spans may differ from legacy by leading-trivia bytes: the Kuzu writer
  stores spans from the SV builder which include leading trivia, while the
  legacy exporter derived token spans from ``location.offset + len(rawText)``.
  Non-token spans match.

Run: ``uv run python research/ast_experiment/scripts/export_demo_graph_kuzu.py``
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent.parent
_REPO_ROOT = _HERE.parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from knowledge_graph import cypher, extract, open_store, source_at  # noqa: E402

# The writer's edge-table map is the inverse of what we need; importing it
# means we don't double-maintain the legacy-edge-type -> rel-table mapping.
# This is intentionally an internal-package import: it's static metadata that
# doesn't ship through the Kuzu graph (no payload-level "type" string).
# Marked with a noqa-equivalent comment so reviewers know to keep this in
# sync if the writer's map changes.
from knowledge_graph.builders.sv.writer import EDGE_TABLE_MAP  # noqa: E402
from knowledge_graph.builders.sv.semantic.rules import (  # noqa: E402
    ALL_RULE_MODULES,
)

CORPUS_DIR = _HERE / "corpus"
OUT_PATH = _HERE / "demo" / "data" / "graph.json"
BUCKET1_PATH = _HERE / "BUCKET_1_CHECKLIST.md"
SCHEMA_VERSION = "1"
EXPORTER_TAG = "export_demo_graph_kuzu.py"


# --------------------------------------------------------------------------- #
# Bucket-1 categorisation (shared logic — copied verbatim from the legacy     #
# exporter to keep the two scripts independently runnable; promote to a       #
# shared module the moment the legacy script is deleted).                     #
# --------------------------------------------------------------------------- #


def _parse_bucket1_categories() -> dict[str, str]:
    """Parse ``BUCKET_1_CHECKLIST.md`` into ``{SyntaxKindName: category}``."""
    text = BUCKET1_PATH.read_text()
    out: dict[str, str] = {}
    section: str | None = None
    section_map = {
        "PROMOTE": "semantic",
        "CONTAINER": "structural",
        "BLOB": "blob",
        "DIRECTIVE": "structural",
        "OUT-OF-SCOPE": "structural",
    }
    for line in text.splitlines():
        m = re.match(r"^## ([A-Z\-]+)\s*\(", line)
        if m and m.group(1) in section_map:
            section = section_map[m.group(1)]
            continue
        if section is None:
            continue
        m2 = re.match(r"^\|\s*`([A-Za-z0-9_]+)`", line)
        if m2:
            out[m2.group(1)] = section
    return out


_BUCKET1 = _parse_bucket1_categories()


def _resolve_category(
    *, kuzu_category: str, is_token: bool, kind: str, has_semantic: bool
) -> str:
    """Apply SPEC §3.3 categorisation on top of the Kuzu-stored category.

    The writer collapses non-queryable / non-token rows to ``"structural"``;
    SPEC §3.3 further splits those into ``"structural"`` vs ``"blob"`` using
    ``BUCKET_1_CHECKLIST.md``. We never demote the writer's ``semantic`` /
    ``token`` labels.
    """
    if is_token:
        return "token"
    if has_semantic or kuzu_category == "semantic":
        return "semantic"
    short = kind.split(".")[-1] if isinstance(kind, str) else ""
    cat = _BUCKET1.get(short)
    if cat is not None:
        return cat
    return "structural"


# --------------------------------------------------------------------------- #
# Byte-offset → char-offset projection (for FE string-slicing of inlined src) #
# --------------------------------------------------------------------------- #


def _byte_to_char_map(text: str) -> list[int]:
    """Build ``byte_offset -> char_offset`` lookup for an inlined source string."""
    table = [0] * (len(text.encode("utf-8")) + 1)
    byte_pos = 0
    for char_pos, ch in enumerate(text):
        n = len(ch.encode("utf-8"))
        for k in range(n):
            table[byte_pos + k] = char_pos
        byte_pos += n
    table[byte_pos] = len(text)
    return table


def _project_span(
    *,
    file_id: str,
    byte_start: int,
    byte_end: int,
    start_line: int,
    end_line: int,
    start_col: int,
    end_col: int,
    b2c: list[int],
    source_len: int,
) -> dict[str, Any] | None:
    """Project Kuzu's stored byte-span columns into the FE-facing span dict.

    Returns ``None`` when the row has the "missing span" sentinel (-1, -1)
    that the writer uses for synthetic / unresolved nodes, or when the
    projection would land on an empty range.
    """
    if byte_start < 0 or byte_end < 0:
        return None
    if byte_end <= byte_start:
        return None
    last = len(b2c) - 1
    c_start = b2c[byte_start] if 0 <= byte_start <= last else byte_start
    if byte_end >= last:
        c_end = b2c[last]
    elif byte_end >= 0:
        c_end = b2c[byte_end]
    else:
        c_end = byte_end
    if c_end > source_len:
        c_end = source_len
    if c_start >= c_end:
        return None
    return {
        "file": file_id,
        "startOffset": c_start,
        "endOffset": c_end,
        "startLine": int(start_line) if start_line else 1,
        "endLine": int(end_line) if end_line else int(start_line or 1),
        "startCol": int(start_col) if start_col else 1,
        "endCol": int(end_col) if end_col else 1,
    }


# --------------------------------------------------------------------------- #
# Rule-family rollup (SPEC §4) — kind_to_rule built from internal rule modules#
# --------------------------------------------------------------------------- #


def _build_kind_to_rule_id() -> dict[str, str]:
    """``SyntaxKind.<name>`` (stringified) → ``"S<N>"`` from the rule registry."""
    out: dict[str, str] = {}
    for mod in ALL_RULE_MODULES:
        for kind, fn in getattr(mod, "RULES", []):
            rid = getattr(fn, "__rule_id__", None)
            if rid:
                out[str(kind)] = rid
    return out


# Family ids and rule rosters per SPEC §4 — duplicated from the legacy
# exporter (kept in lock-step intentionally; the legacy file stays for the
# transition period and the diff test asserts equivalence).
RULE_FAMILIES: list[dict[str, Any]] = [
    {
        "id": "structure",
        "title": "Module / Interface / Package / Program structure",
        "ruleIds": ["S1", "S11a", "S11b", "S12b", "S12c", "S30"],
        "blurb": "Top-level scopes (module, interface, package, program) and their nested generate / modport children.",
    },
    {
        "id": "ports_params",
        "title": "Ports & parameters",
        "ruleIds": ["S1", "S2", "S3", "S7", "S64", "S65", "S74", "S75", "S76", "S77", "S78"],
        "blurb": "ANSI / non-ANSI port lists, parameter declarations, and parameter overrides on instances.",
    },
    {
        "id": "nets_vars",
        "title": "Nets & variables",
        "ruleIds": ["S4"],
        "blurb": "Net and variable declarations, including identifier references that resolve back to declarators.",
    },
    {
        "id": "continuous_assign_dataflow",
        "title": "Continuous assigns + dataflow",
        "ruleIds": ["S5", "S33", "S34", "S35", "S36", "S37", "S38", "S39"],
        "blurb": "Continuous assigns, their LHS / RHS dataflow edges, and always-block flavours that drive nets.",
    },
    {
        "id": "procedural_blocks",
        "title": "Procedural blocks",
        "ruleIds": ["S7", "S8", "S9", "S9c", "S19", "S20", "S21"],
        "blurb": "always_comb / always_ff / initial / final blocks and the procedural statements inside them.",
    },
    {
        "id": "instances_hierarchy",
        "title": "Instances & hierarchy",
        "ruleIds": ["S6", "S28", "S79"],
        "blurb": "Hierarchical module instantiations and checker instantiations forming the design hierarchy.",
    },
    {
        "id": "assertions_clocking",
        "title": "Assertions & clocking",
        "ruleIds": ["S14", "S15", "S16", "S17", "S18", "S40", "S59", "S70", "S71", "S72"],
        "blurb": "Concurrent / immediate assertions, properties, sequences, and the clocking blocks they synchronise with.",
    },
    {
        "id": "covergroups",
        "title": "Covergroups",
        "ruleIds": ["S22", "S23", "S41"],
        "blurb": "Covergroup declarations, coverpoints, cross coverage, and the bins that drive them.",
    },
    {
        "id": "classes_constraints",
        "title": "Classes & constraints",
        "ruleIds": ["S24", "S25", "S26", "S27", "S82", "S83"],
        "blurb": "Class declarations with inheritance, methods, properties, and constraint blocks.",
    },
    {
        "id": "packages_types_externs",
        "title": "Packages, types & externs",
        "ruleIds": ["S29", "S31", "S32", "S40", "S44", "S45", "S56", "S57", "S80", "S81"]
                   + [f"S{n}" for n in range(40, 58)],
        "blurb": "Package imports/exports, typedefs, DPI imports/exports, and extern declarations bridging compilation units.",
    },
]


def _attribute_to_family(
    node: dict[str, Any], kind_to_rule: dict[str, str]
) -> tuple[str | None, str | None]:
    sem = node.get("semantic") or {}
    rid = sem.get("ruleId") or kind_to_rule.get(str(node.get("kind", "")))
    if rid is None:
        return None, None
    for fam in RULE_FAMILIES:
        if rid in fam["ruleIds"]:
            return rid, fam["id"]
    return rid, None


# --------------------------------------------------------------------------- #
# Read-back helpers (all via the public facade)                               #
# --------------------------------------------------------------------------- #


def _read_origins(store, corpus: str) -> list[dict[str, Any]]:
    """Return the ``:Origin`` rows owned by ``(source='sv', corpus=corpus)``.

    Each row carries the bytes (via ``source_at``) plus the (uri, sha, id)
    needed to namespace nodes back to a file prefix.
    """
    res = cypher(
        store,
        """
        MATCH (o:Origin)
        WHERE o.source = 'sv' AND o.corpus = $corpus
        RETURN o.id, o.uri, o.sha256, o.byte_length
        ORDER BY o.uri ASC
        """,
        {"corpus": corpus},
    )
    out = []
    for row in res.rows:
        out.append({
            "id": row["o.id"],
            "uri": row["o.uri"],
            "sha256": row["o.sha256"],
            "byte_length": int(row["o.byte_length"]),
        })
    return out


def _read_nodes(store, corpus: str) -> list[dict[str, Any]]:
    """Return every ``:Node`` row written under this corpus."""
    res = cypher(
        store,
        """
        MATCH (n:Node)
        WHERE n.source = 'sv' AND n.corpus = $corpus
        RETURN n.id, n.kind, n.category, n.name, n.origin_id,
               n.start_offset, n.end_offset,
               n.start_line, n.end_line, n.start_col, n.end_col,
               n.payload
        ORDER BY n.id ASC
        """,
        {"corpus": corpus},
    )
    out = []
    for row in res.rows:
        payload_raw = row.get("n.payload")
        try:
            payload_obj = json.loads(payload_raw) if payload_raw else {}
        except (TypeError, json.JSONDecodeError):
            payload_obj = {}
        out.append({
            "id": row["n.id"],
            "kind": row.get("n.kind") or "",
            "category_raw": row.get("n.category") or "structural",
            "name": row.get("n.name"),
            "origin_id": row.get("n.origin_id"),
            "byte_start": int(row["n.start_offset"]) if row.get("n.start_offset") is not None else -1,
            "byte_end": int(row["n.end_offset"]) if row.get("n.end_offset") is not None else -1,
            "start_line": int(row.get("n.start_line") or 0),
            "end_line": int(row.get("n.end_line") or 0),
            "start_col": int(row.get("n.start_col") or 0),
            "end_col": int(row.get("n.end_col") or 0),
            "payload_blob": payload_obj,
        })
    return out


def _read_edges(store, known_ids: set[str]) -> list[dict[str, Any]]:
    """One cypher query per rel table; reconstruct legacy edge entries.

    Skips edges whose endpoints are outside ``known_ids`` (e.g. cross-corpus
    references that would be ambiguous to attribute). In practice every demo
    edge stays inside the demo corpus because the SV builder doesn't cross
    extract boundaries.
    """
    # Invert EDGE_TABLE_MAP: rel-table-name -> (legacy_type, payload_cols)
    inverse: dict[str, tuple[str, list[str]]] = {}
    # We need the extra column names per edge type; mirror the writer logic.
    # Rather than re-introspecting the extractor, we hard-code the rel
    # column names below to keep the read query self-describing. This table
    # MUST stay in sync with ``EDGE_TABLE_MAP``; the structural-diff test
    # asserts every legacy edge type round-trips and would surface a drift.
    cols_for_type: dict[str, list[str]] = {
        "child": ["ordinal"],
        "sensitive_to": ["edge"],
        "connects": ["instance", "port"],
        "param_override": ["name", "value"],
        "has_enum_value": ["name", "typedef"],
        "extends": ["name", "params"],
        "implements": ["name"],
        "of_checker": ["name"],
        "default_clocking": ["name"],
        "references_interface": ["modport"],
        "dpi_exports": ["spec", "export_kind", "unresolved"],
        "imports": ["package", "item", "unresolved"],
        "imports_item": ["package", "symbol"],
        "exports_all": ["wildcard"],
        "declares": ["name", "kind"],
        "bind_target": ["target", "target_module", "ordinal", "unresolved"],
        "bound_into": ["instance_name", "scope"],
        "defparam_override": ["hier_path", "value", "unresolved"],
    }
    for legacy_type, (table, _extractor) in EDGE_TABLE_MAP.items():
        inverse[table] = (legacy_type, cols_for_type.get(legacy_type, []))

    edges: list[dict[str, Any]] = []
    for table, (legacy_type, cols) in inverse.items():
        col_select = "".join(f", r.{c}" for c in cols)
        q = (
            f"MATCH (a:Node)-[r:{table}]->(b:Node) "
            f"RETURN a.id, b.id{col_select}"
        )
        res = cypher(store, q)
        for row in res.rows:
            src = row["a.id"]
            dst = row["b.id"]
            if src not in known_ids or dst not in known_ids:
                continue
            payload: dict[str, Any] = {}
            for c in cols:
                v = row.get(f"r.{c}")
                if legacy_type == "child" and c == "ordinal":
                    payload["index"] = int(v or 0)
                else:
                    if v is None or v == "":
                        continue
                    payload[c] = v
            edges.append({
                "src": src,
                "dst": dst,
                "type": legacy_type,
                "payload": payload,
            })
    return edges


# --------------------------------------------------------------------------- #
# Main export                                                                 #
# --------------------------------------------------------------------------- #


def _prefix_of(node_id: str) -> str:
    idx = node_id.find(":")
    return node_id[:idx] if idx >= 0 else ""


def _project_node(
    n: dict[str, Any], span: dict[str, Any] | None
) -> dict[str, Any]:
    blob = n["payload_blob"]
    legacy_payload = blob.get("payload", {}) if isinstance(blob, dict) else {}
    type_name = blob.get("type", "") if isinstance(blob, dict) else ""
    is_token = bool(n["kind"].startswith("TokenKind."))
    has_semantic = isinstance(blob, dict) and "semantic" in blob
    category = _resolve_category(
        kuzu_category=n["category_raw"],
        is_token=is_token,
        kind=n["kind"],
        has_semantic=has_semantic,
    )
    out: dict[str, Any] = {
        "id": n["id"],
        "type": type_name,
        "kind": n["kind"],
        "isToken": is_token,
        "category": category,
        "span": span,
        "payload": legacy_payload or {},
    }
    if has_semantic:
        out["semantic"] = blob["semantic"]
    if isinstance(blob, dict) and blob.get("queryable"):
        out["queryable"] = True
    return out


def export(
    corpus_files: list[Path],
    out_path: Path,
    *,
    store_dir: Path | None = None,
    corpus: str = "demo",
) -> dict[str, Any]:
    """Build the demo graph artifact via the public facade and write it."""
    # Use a throwaway store dir unless the caller pins one (the tests pin
    # for cache reuse across xdist workers).
    cleanup_store = store_dir is None
    if store_dir is None:
        store_dir = Path(tempfile.mkdtemp(prefix="kgweave-demo-export-"))
    store_path = store_dir / "demo.kuzu"

    try:
        store = open_store(store_path)
        try:
            extract(store, source="sv", corpus=corpus, paths=corpus_files)

            # ----- read back origins -> build files[] --------------------
            origins = _read_origins(store, corpus)
            # Map uri -> origin row for prefix attribution later.
            origin_by_id: dict[str, dict[str, Any]] = {o["id"]: o for o in origins}
            # Get the source bytes for each origin.
            for o in origins:
                raw = source_at(store, o["id"], 0, o["byte_length"])
                o["source_bytes"] = raw
                o["source_text"] = raw.decode("utf-8", errors="replace")

            # ----- read nodes --------------------------------------------
            all_nodes = _read_nodes(store, corpus)
            # ``_unresolved.*`` placeholder rows are Phase-C.5 sentinels the
            # writer materializes to keep rel-table FK constraints satisfied.
            # The legacy exporter never emitted them as ``nodes[]`` entries —
            # but it DID emit edges pointing at them. Mirror that: drop the
            # placeholders from the node projection but keep them in the
            # ``known_ids`` set so the edge query doesn't skip those edges.
            raw_nodes = [n for n in all_nodes if n["category_raw"] != "unresolved"]
            known_ids = {n["id"] for n in all_nodes}

            # Map prefix -> origin row by inspecting the first node owned by
            # each origin id. The SV writer always pairs every node with an
            # origin; the prefix-to-origin relation is 1:1 by construction.
            prefix_to_origin: dict[str, dict[str, Any]] = {}
            for n in raw_nodes:
                p = _prefix_of(n["id"])
                if p and p not in prefix_to_origin:
                    o = origin_by_id.get(n["origin_id"])
                    if o is not None:
                        prefix_to_origin[p] = o

            # Build files[] in deterministic order (corpus_files order).
            file_entries: list[dict[str, Any]] = []
            seen_prefix: dict[str, int] = {}
            for sv_path in corpus_files:
                stem = sv_path.stem
                n_seen = seen_prefix.get(stem, 0)
                seen_prefix[stem] = n_seen + 1
                prefix = stem if n_seen == 0 else f"{stem}{n_seen}"
                o = prefix_to_origin.get(prefix)
                if o is None:
                    # Origin exists but no node was written — surface via empty file entry.
                    src_text = sv_path.read_text()
                else:
                    src_text = o["source_text"]
                file_entries.append({
                    "id": prefix,
                    "path": str(sv_path.relative_to(_REPO_ROOT)),
                    "source": src_text,
                    "lineCount": src_text.count("\n") + (
                        0 if src_text.endswith("\n") else 1
                    ),
                    "rootNodeId": _find_root_node_id(raw_nodes, prefix),
                })

            # Precompute byte->char tables per file id.
            b2c_by_file: dict[str, list[int]] = {}
            srclen_by_file: dict[str, int] = {}
            for f in file_entries:
                b2c_by_file[f["id"]] = _byte_to_char_map(f["source"])
                srclen_by_file[f["id"]] = len(f["source"])

            # ----- project nodes -----------------------------------------
            projected_nodes: list[dict[str, Any]] = []
            spans_by_id: dict[str, dict[str, Any] | None] = {}
            for n in raw_nodes:
                file_id = _prefix_of(n["id"])
                b2c = b2c_by_file.get(file_id)
                if b2c is None:
                    span = None
                else:
                    span = _project_span(
                        file_id=file_id,
                        byte_start=n["byte_start"],
                        byte_end=n["byte_end"],
                        start_line=n["start_line"],
                        end_line=n["end_line"],
                        start_col=n["start_col"],
                        end_col=n["end_col"],
                        b2c=b2c,
                        source_len=srclen_by_file[file_id],
                    )
                spans_by_id[n["id"]] = span
                projected_nodes.append(_project_node(n, span))

            # Deterministic node order: by file (corpus order), then by node id.
            file_order = {f["id"]: i for i, f in enumerate(file_entries)}
            projected_nodes.sort(
                key=lambda x: (
                    file_order.get(_prefix_of(x["id"]), len(file_order)),
                    x["id"],
                )
            )

            # ----- project edges -----------------------------------------
            raw_edges = _read_edges(store, known_ids)
            # Deterministic edge order: by src, type, dst, then payload-string.
            raw_edges.sort(
                key=lambda e: (
                    file_order.get(_prefix_of(e["src"]), len(file_order)),
                    e["src"],
                    e["type"],
                    e["dst"],
                    json.dumps(e["payload"], sort_keys=True),
                )
            )
            projected_edges: list[dict[str, Any]] = []
            for i, e in enumerate(raw_edges):
                projected_edges.append({
                    "id": f"e{i:05d}",
                    "src": e["src"],
                    "dst": e["dst"],
                    "type": e["type"],
                    "span": spans_by_id.get(e["src"]),
                    "payload": e["payload"],
                })

            # ----- rule families rollup ----------------------------------
            kind_to_rule = _build_kind_to_rule_id()
            exemplars: dict[str, list[str]] = {f["id"]: [] for f in RULE_FAMILIES}
            for n in projected_nodes:
                _rid, fam_id = _attribute_to_family(n, kind_to_rule)
                if fam_id is None:
                    continue
                bucket = exemplars[fam_id]
                if len(bucket) < 5:
                    bucket.append(n["id"])

            rule_families_out: list[dict[str, Any]] = []
            for fam in RULE_FAMILIES:
                rule_families_out.append({
                    "id": fam["id"],
                    "title": fam["title"],
                    "ruleIds": sorted(set(fam["ruleIds"])),
                    "exemplarNodeIds": exemplars[fam["id"]],
                    "blurb": fam["blurb"],
                })

            # ----- stats + envelope --------------------------------------
            semantic_node_count = sum(
                1 for n in projected_nodes if n.get("semantic")
            )
            semantic_edge_count = sum(
                1 for e in projected_edges if e["type"] != "child"
            )

            artifact = {
                "version": SCHEMA_VERSION,
                "generatedAt": _dt.datetime.now(_dt.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "exporter": EXPORTER_TAG,
                "files": file_entries,
                "nodes": projected_nodes,
                "edges": projected_edges,
                "ruleFamilies": rule_families_out,
                "stats": {
                    "nodeCount": len(projected_nodes),
                    "edgeCount": len(projected_edges),
                    "semanticNodeCount": semantic_node_count,
                    "semanticEdgeCount": semantic_edge_count,
                },
            }

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(artifact, separators=(",", ":")))
            return artifact
        finally:
            store.close()
    finally:
        if cleanup_store:
            shutil.rmtree(store_dir, ignore_errors=True)


def _find_root_node_id(nodes: list[dict[str, Any]], prefix: str) -> str:
    """Return the lexicographically-first node id under ``prefix`` (matches
    build_kg's ``n0001`` root)."""
    candidates = [n["id"] for n in nodes if _prefix_of(n["id"]) == prefix]
    if not candidates:
        return f"{prefix}:n0001.SyntaxTree"
    return min(candidates)


def main() -> int:
    corpus_files = sorted(CORPUS_DIR.glob("*.sv"))
    if not corpus_files:
        print(f"no corpus files found under {CORPUS_DIR}", file=sys.stderr)
        return 2
    artifact = export(corpus_files, OUT_PATH)
    print(
        f"wrote {OUT_PATH.relative_to(_REPO_ROOT)} — "
        f"{artifact['stats']['nodeCount']} nodes, "
        f"{artifact['stats']['edgeCount']} edges, "
        f"{len(artifact['files'])} files, "
        f"{artifact['stats']['semanticNodeCount']} queryable"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
