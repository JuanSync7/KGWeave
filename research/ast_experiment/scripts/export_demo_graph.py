"""Export the pyslang AST KG to ``demo/data/graph.json`` for the GH-Pages demo.

This is the SA2 deliverable in the static demo pipeline. It:

1. Calls :func:`build_kg` on every ``corpus/*.sv`` file to get
   ``(graph, trees, compilation)``.
2. For every node in ``graph['nodes']`` that was emitted by lift, walks the
   matching ``SyntaxTree`` in the same DFS order lift uses and attaches a
   ``span`` dict (file/startOffset/endOffset/startLine/endLine/startCol/endCol).
   Synthetic semantic-only nodes (``role:hier.path`` ids added by promote)
   get ``span: null``.
3. Annotates each node with ``category`` (``semantic`` / ``structural`` /
   ``blob`` / ``token``) parsed from ``BUCKET_1_CHECKLIST.md``.
4. Attaches ``span`` to every edge — equal to the SOURCE NODE's span
   (SA1 decision; see ``demo/SPEC.md`` §3.4).
5. Inlines every corpus file's raw text in ``files[]`` so the FE never
   re-fetches source.
6. Computes ``ruleFamilies`` rollup per ``SPEC.md`` §4 by attributing
   queryable nodes to S-rule ids (via ``__rule_id__`` on rule callables)
   and grouping into the 10 family ids.

The exporter is the only consumer of pyslang at demo build time; the
frontend reads the emitted JSON and never re-parses.

Run: ``uv run python research/ast_experiment/scripts/export_demo_graph.py``
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent.parent
_REPO_ROOT = _HERE.parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pyslang  # noqa: E402

from scripts._demo_common import (  # noqa: E402
    RULE_FAMILIES,
    attribute_to_family as _attribute_node_to_family,
    category_for_kind,
    parse_bucket1_categories,
)
from src.build import build_kg  # noqa: E402
from src.semantic.rules import ALL_RULE_MODULES  # noqa: E402

CORPUS_DIR = _HERE / "corpus"
OUT_PATH = _HERE / "demo" / "data" / "graph.json"
BUCKET1_PATH = _HERE / "BUCKET_1_CHECKLIST.md"
SCHEMA_VERSION = "1"


# --------------------------------------------------------------------------- #
# Bucket-1 categorisation (table + resolver live in ``_demo_common``)         #
# --------------------------------------------------------------------------- #


_BUCKET1 = parse_bucket1_categories(BUCKET1_PATH)


def _category_for(node: dict[str, Any]) -> str:
    """Resolve the SPEC §3.3 category for an in-memory graph node."""
    return category_for_kind(
        _BUCKET1,
        kind=node.get("kind", "") or "",
        is_token=bool(node.get("is_token") or node.get("isToken")),
        is_semantic=bool(node.get("semantic") or node.get("queryable")),
    )


# --------------------------------------------------------------------------- #
# Span attachment via DFS walk of each SyntaxTree                             #
# --------------------------------------------------------------------------- #


def _dfs_pyslang(root: Any):
    """Yield every pyslang node in the SAME pre-order ``src.lift._Builder.visit`` uses.

    Lift visits the root, then iterates ``list(node)`` and recurses. We
    replicate that exact traversal so node[i] in lift-order maps to the i-th
    yielded pyslang node.
    """
    yield root
    try:
        children = list(root)
    except TypeError:
        return
    for c in children:
        if c is None:
            continue
        yield from _dfs_pyslang(c)


def _byte_to_char_map(text: str) -> list[int]:
    """Build a table mapping UTF-8 byte offset → character offset.

    pyslang reports source ranges as byte offsets into the UTF-8-encoded
    buffer; the inlined ``source`` we send to the FE is a Python string
    (character-indexed). When the corpus contains multi-byte chars the two
    offsets diverge — convert here so the FE can do simple ``source[start:end]``.
    """
    table = [0] * (len(text.encode("utf-8")) + 1)
    byte_pos = 0
    for char_pos, ch in enumerate(text):
        n = len(ch.encode("utf-8"))
        for k in range(n):
            table[byte_pos + k] = char_pos
        byte_pos += n
    table[byte_pos] = len(text)
    return table


def _span_for_node(pn: Any, sm: Any, file_id: str, b2c: list[int] | None = None) -> dict[str, Any] | None:
    """Build the span dict for a pyslang node or token.

    For tokens we derive end-offset from ``location.offset + len(rawText)``
    (per SA1 probe — tokens have no ``sourceRange``). For syntax nodes we
    read ``sourceRange.start`` and ``sourceRange.end`` directly.
    """
    is_token = type(pn).__name__ == "Token"
    try:
        if is_token:
            start_off = int(pn.location.offset)
            raw = pn.rawText or ""
            end_off = start_off + len(raw)
            start_loc = pn.location
            end_loc = None  # derived below
        else:
            sr = pn.sourceRange
            start_loc = sr.start
            end_loc = sr.end
            start_off = int(start_loc.offset)
            end_off = int(end_loc.offset)
    except Exception:
        return None
    if end_off <= start_off:
        if is_token and end_off == start_off:
            # Zero-width token (e.g. missing) — emit a degenerate span the FE can ignore.
            return None
        return None
    # Capture byte offsets BEFORE we project to char offsets so the line/col
    # source-manager calls (below) still see the original byte locations.
    byte_start, byte_end = start_off, end_off
    try:
        start_line = int(sm.getLineNumber(start_loc))
        start_col = int(sm.getColumnNumber(start_loc))
    except Exception:
        start_line = 1
        start_col = 1
    if is_token:
        # Tokens don't have an explicit end location; approximate by start.
        end_line = start_line
        end_col = start_col + (end_off - start_off)
    else:
        try:
            end_line = int(sm.getLineNumber(end_loc))
            end_col = int(sm.getColumnNumber(end_loc))
        except Exception:
            end_line = start_line
            end_col = start_col
    if b2c is not None:
        # Project byte offsets → character offsets so the FE can index the
        # inlined source string directly.
        last = len(b2c) - 1
        if 0 <= byte_start <= last:
            start_off = b2c[byte_start]
        if 0 <= byte_end <= last:
            end_off = b2c[byte_end]
        elif byte_end >= last:
            end_off = b2c[last]
    return {
        "file": file_id,
        "startOffset": start_off,
        "endOffset": end_off,
        "startLine": start_line,
        "endLine": end_line,
        "startCol": start_col,
        "endCol": end_col,
    }


# --------------------------------------------------------------------------- #
# Rule ownership rollup                                                       #
# --------------------------------------------------------------------------- #


def _build_kind_to_rule_id() -> dict[str, str]:
    """Map ``SyntaxKind.<name>`` (stringified) → ``"S<N>"`` from rule modules."""
    out: dict[str, str] = {}
    for mod in ALL_RULE_MODULES:
        for kind, fn in getattr(mod, "RULES", []):
            rid = getattr(fn, "__rule_id__", None)
            if rid:
                out[str(kind)] = rid
    return out


# Family priority for choosing exemplars when a rule appears in multiple families.
_FAMILY_PRIORITY: dict[str, int] = {fam["id"]: i for i, fam in enumerate(RULE_FAMILIES)}


# --------------------------------------------------------------------------- #
# Main export                                                                 #
# --------------------------------------------------------------------------- #


def _project_node(n: dict[str, Any], span: dict[str, Any] | None) -> dict[str, Any]:
    """Project an in-memory graph node into the SPEC §3.3 NodeEntry shape."""
    out: dict[str, Any] = {
        "id": n["id"],
        "type": n.get("type", ""),
        "kind": n.get("kind", ""),
        "isToken": bool(n.get("is_token", False)),
        "category": _category_for(n),
        "span": span,
        "payload": n.get("payload", {}) or {},
    }
    if "semantic" in n:
        out["semantic"] = n["semantic"]
    if n.get("queryable"):
        out["queryable"] = True
    return out


def export(corpus_files: list[Path], out_path: Path) -> dict[str, Any]:
    """Build the demo graph artifact and write it to ``out_path``."""
    graph, trees, _compilation = build_kg(corpus_files)

    # Index graph nodes by id for fast lookup.
    nodes_by_id: dict[str, dict[str, Any]] = {n["id"]: n for n in graph["nodes"]}

    # ------------------------------------------------------------------ #
    # 1. Walk every tree in lift's DFS order; attach spans to its slice. #
    # ------------------------------------------------------------------ #
    spans: dict[str, dict[str, Any] | None] = {n["id"]: None for n in graph["nodes"]}
    file_entries: list[dict[str, Any]] = []
    # Reconstruct the prefix and offset for each tree (same logic as build_kg).
    seen_prefixes: dict[str, int] = {}
    cursor = 0
    for tree, sv_path in zip(trees, corpus_files):
        stem = sv_path.stem
        n_seen = seen_prefixes.get(stem, 0)
        seen_prefixes[stem] = n_seen + 1
        prefix = stem if n_seen == 0 else f"{stem}{n_seen}"
        sm = tree.sourceManager
        source_text = sv_path.read_text()
        b2c = _byte_to_char_map(source_text)

        # Replicate lift's DFS and zip with the corresponding nodes slice.
        ordered_pys = list(_dfs_pyslang(tree.root))
        count = len(ordered_pys)
        slice_nodes = graph["nodes"][cursor:cursor + count]
        source_len = len(source_text)
        assert len(slice_nodes) == count, (
            f"slice/dfs mismatch on {prefix}: {len(slice_nodes)} vs {count}"
        )
        # Sanity: prefix matches for the slice.
        if slice_nodes:
            first_id = slice_nodes[0]["id"]
            assert first_id.startswith(prefix + ":"), (
                f"prefix mismatch — first slice id={first_id!r} prefix={prefix!r}"
            )
        for pn, gn in zip(ordered_pys, slice_nodes):
            sp = _span_for_node(pn, sm, prefix, b2c=b2c)
            if sp is not None:
                # pyslang's source range can extend one past EOF for the
                # CompilationUnit (synthetic EOF token). Clamp so FE slicing
                # against the inlined source never goes out of bounds.
                if sp["endOffset"] > source_len:
                    sp["endOffset"] = source_len
                if sp["startOffset"] >= sp["endOffset"]:
                    sp = None
            spans[gn["id"]] = sp

        # File entry.
        root_id = slice_nodes[0]["id"] if slice_nodes else f"{prefix}:n0001.SyntaxTree"
        file_entries.append({
            "id": prefix,
            "path": str(sv_path.relative_to(_REPO_ROOT)),
            "source": source_text,
            "lineCount": source_text.count("\n") + (0 if source_text.endswith("\n") else 1),
            "rootNodeId": root_id,
        })
        cursor += count

    # ------------------------------------------------------------------ #
    # 2. Project nodes.                                                  #
    # ------------------------------------------------------------------ #
    projected_nodes = [_project_node(n, spans[n["id"]]) for n in graph["nodes"]]

    # ------------------------------------------------------------------ #
    # 3. Project edges; attach source-node span.                         #
    # ------------------------------------------------------------------ #
    projected_edges: list[dict[str, Any]] = []
    for i, e in enumerate(graph["edges"]):
        src_span = spans.get(e["src"])
        payload = dict(e.get("payload", {}) or {})
        # Attribute semantic edges to their rule id if known.
        proj = {
            "id": f"e{i:05d}",
            "src": e["src"],
            "dst": e["dst"],
            "type": e["type"],
            "span": src_span,
            "payload": payload,
        }
        projected_edges.append(proj)

    # ------------------------------------------------------------------ #
    # 4. Rule families rollup.                                           #
    # ------------------------------------------------------------------ #
    kind_to_rule = _build_kind_to_rule_id()
    exemplars: dict[str, list[str]] = {fam["id"]: [] for fam in RULE_FAMILIES}
    for n in projected_nodes:
        rid, fam_id = _attribute_node_to_family(n, kind_to_rule)
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

    # ------------------------------------------------------------------ #
    # 5. Stats + envelope.                                               #
    # ------------------------------------------------------------------ #
    semantic_node_count = sum(1 for n in projected_nodes if n.get("semantic"))
    # Semantic edges = edges whose payload carries a ruleId (or non-"child"
    # edges synthesised by S-rules).
    semantic_edge_count = sum(1 for e in projected_edges if e["type"] != "child")

    artifact = {
        "version": SCHEMA_VERSION,
        "generatedAt": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": file_entries,
        "nodes": projected_nodes,
        "edges": projected_edges,
        "ruleFamilies": rule_families_out,
        "stats": {
            "nodeCount": len(projected_nodes),
            "edgeCount": len(projected_edges),
            "semanticNodeCount": semantic_node_count,
            "semanticEdgeCount": semantic_edge_count,
            # Legacy in-memory exporter has no GC concept; emit 0 for shape
            # parity with the Kuzu-port exporter (v1.5-#6).
            "gc_pruned": 0,
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, separators=(",", ":")))
    return artifact


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
