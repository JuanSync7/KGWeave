"""Forward: pyslang SyntaxTree -> graph (nodes, edges, order).

Lift is class-agnostic and structural. For every pyslang syntax node we create
a graph node typed by class name + SyntaxKind, and for every child reachable
by iter(node) we add an ordered "child" edge to the corresponding graph node.

Token leaves carry their lexical payload (kind, rawText, leading trivia) so the
reverse engine can reconstruct text without consulting source strings. No regex
is used; child enumeration relies solely on pyslang's iterable SyntaxNode API.

Every emitted graph node carries a ``span`` dict with byte offsets and line/col
positions resolved from pyslang's ``sourceRange`` (for SyntaxNodes) or from
``location.offset`` + trivia/rawText byte lengths (for Tokens). Synthetic
SyntaxList nodes whose pyslang range is the sentinel ``0xFFFFFFFFF`` fall back
to the union of their valid descendants' spans.

Token-span semantics (decision): leading trivia *is* included in the token
span so that ``file_bytes[start_offset:end_offset] == trivia_text + rawText``
(matching the lossless-emit invariant). pyslang's SyntaxNode ``sourceRange``
already excludes leading trivia of its first token, so syntax-node spans use
the raw sourceRange offsets.

Graph shape::

    {
      "nodes": [
        {"id": str, "type": class_name, "kind": syntax_or_token_kind,
         "is_token": bool,
         "span": {"start_offset": int, "end_offset": int,
                  "start_line": int, "end_line": int,
                  "start_col": int, "end_col": int} | None,
         "payload": {...}},
        ...
      ],
      "edges": [
        {"src": parent_id, "dst": child_id, "type": "child",
         "payload": {"index": int}},
        ...
      ],
      "order": [root_id],
    }
"""

from __future__ import annotations

from typing import Any

# pyslang uses this sentinel for synthetic / null SourceLocations
# (observed value 0xFFFFFFFFF = 68719476735).
_INVALID_OFFSET = 0xFFFFFFFFF


def _trivia_records(token: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for tr in token.trivia:
        out.append({"kind": str(tr.kind), "text": tr.getRawText()})
    return out


def _safe_line_col(sm: Any, loc: Any) -> tuple[int | None, int | None]:
    if sm is None or loc is None:
        return None, None
    try:
        line = int(sm.getLineNumber(loc))
    except Exception:
        line = None
    try:
        col = int(sm.getColumnNumber(loc))
    except Exception:
        col = None
    return line, col


def _token_span(token: Any, sm: Any) -> dict[str, Any]:
    """Span for a Token = (loc - trivia_bytes, loc + rawText_bytes)."""
    raw = token.rawText or ""
    trivia_text = "".join(tr.getRawText() for tr in token.trivia)
    raw_bytes = len(raw.encode("utf-8"))
    trivia_bytes = len(trivia_text.encode("utf-8"))
    loc = token.location
    start_offset = int(loc.offset) - trivia_bytes
    end_offset = int(loc.offset) + raw_bytes
    # Line/col: pyslang exposes getLineNumber/getColumnNumber on SourceLocation
    # but we only have the rawText start location. The trivia-inclusive start
    # line/col is best-effort: we report the rawText location's line/col.
    start_line, start_col = _safe_line_col(sm, loc)
    end_line = end_col = None
    return {
        "start_offset": start_offset,
        "end_offset": end_offset,
        "start_line": start_line,
        "end_line": end_line,
        "start_col": start_col,
        "end_col": end_col,
    }


def _syntax_span(node: Any, sm: Any) -> dict[str, Any] | None:
    sr = getattr(node, "sourceRange", None)
    if sr is None:
        return None
    s_off = int(sr.start.offset)
    e_off = int(sr.end.offset)
    if s_off >= _INVALID_OFFSET or e_off >= _INVALID_OFFSET:
        return None
    s_line, s_col = _safe_line_col(sm, sr.start)
    e_line, e_col = _safe_line_col(sm, sr.end)
    return {
        "start_offset": s_off,
        "end_offset": e_off,
        "start_line": s_line,
        "end_line": e_line,
        "start_col": s_col,
        "end_col": e_col,
    }


def _merge_spans(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Union span = min(start_offset), max(end_offset) over valid child spans."""
    valid = [s for s in spans if s is not None and s.get("start_offset") is not None]
    if not valid:
        return None
    start = min(s["start_offset"] for s in valid)
    end = max(s["end_offset"] for s in valid)
    # Pick the child span that owns the chosen start/end for line/col.
    s_owner = min(valid, key=lambda s: s["start_offset"])
    e_owner = max(valid, key=lambda s: s["end_offset"])
    return {
        "start_offset": start,
        "end_offset": end,
        "start_line": s_owner.get("start_line"),
        "end_line": e_owner.get("end_line") if e_owner.get("end_line") is not None
        else e_owner.get("start_line"),
        "start_col": s_owner.get("start_col"),
        "end_col": e_owner.get("end_col") if e_owner.get("end_col") is not None
        else e_owner.get("start_col"),
    }


class _Builder:
    def __init__(
        self,
        source_manager: Any | None = None,
        id_prefix: str = "",
        start_counter: int = 0,
    ) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._counter = start_counter
        self._sm = source_manager
        self._id_prefix = id_prefix

    def _new_id(self, cls_name: str) -> str:
        self._counter += 1
        prefix = f"{self._id_prefix}:" if self._id_prefix else ""
        return f"{prefix}n{self._counter:04d}.{cls_name}"

    def visit(self, node: Any) -> tuple[str, dict[str, Any] | None]:
        """Visit a pyslang node. Returns (graph_id, resolved_span)."""
        cls_name = type(node).__name__
        nid = self._new_id(cls_name)
        if cls_name == "Token":
            span = _token_span(node, self._sm)
            line = span.get("start_line")
            payload: dict[str, Any] = {
                "rawText": node.rawText,
                "valueText": node.valueText,
                "trivia": _trivia_records(node),
                "isMissing": bool(node.isMissing),
            }
            if line is not None:
                # Preserve legacy ``payload['source']['line']`` shape that
                # downstream semantic queries expect.
                payload["source"] = {"line": line}
            self.nodes.append({
                "id": nid,
                "type": "Token",
                "kind": str(node.kind),
                "is_token": True,
                "span": span,
                "payload": payload,
            })
            return nid, span

        # Container syntax node — record kind, recurse, then resolve span.
        kind = str(getattr(node, "kind", ""))
        node_record: dict[str, Any] = {
            "id": nid,
            "type": cls_name,
            "kind": kind,
            "is_token": False,
            "span": None,  # back-filled after recursion
            "payload": {},
        }
        self.nodes.append(node_record)
        try:
            children = list(node)
        except TypeError:
            children = []
        child_spans: list[dict[str, Any]] = []
        for idx, child in enumerate(children):
            child_id, child_span = self.visit(child)
            self.edges.append({
                "src": nid,
                "dst": child_id,
                "type": "child",
                "payload": {"index": idx},
            })
            if child_span is not None:
                child_spans.append(child_span)
        # Try pyslang's own sourceRange first; fall back to merged children.
        span = _syntax_span(node, self._sm)
        if span is None:
            span = _merge_spans(child_spans)
        node_record["span"] = span
        return nid, span


def lift(
    tree: Any,
    *,
    graph: dict[str, Any] | None = None,
    id_prefix: str = "",
) -> dict[str, Any]:
    """Convert a pyslang SyntaxTree into the structural graph dict.

    Every emitted node carries a ``span`` field (see module docstring for
    semantics). Token payloads also carry an optional ``source.line`` mirror
    for compatibility with downstream semantic queries.

    If ``graph`` is provided, nodes/edges are appended in place and the same
    dict is returned. ``id_prefix`` namespaces the generated node ids — used
    by :func:`build_kg` to keep ids globally unique across multiple files.
    """
    sm = getattr(tree, "sourceManager", None)
    builder = _Builder(source_manager=sm, id_prefix=id_prefix, start_counter=0)
    root_id, root_span = builder.visit(tree.root)
    _backfill_empty_spans(
        builder.nodes, builder.edges, root_id, root_span
    )
    if graph is None:
        return {
            "nodes": builder.nodes,
            "edges": builder.edges,
            "order": [root_id],
        }
    graph["nodes"].extend(builder.nodes)
    graph["edges"].extend(builder.edges)
    graph.setdefault("order", []).append(root_id)
    return graph


def _backfill_empty_spans(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    root_id: str,
    root_span: dict[str, Any] | None,
) -> None:
    """Give a zero-length span to nodes whose span is still ``None`` after
    recursion (empty SyntaxList sentinels and any other span-less leaves).

    Strategy: walk DFS in original child order; anchor each empty-span node at
    the end_offset of the previous in-order sibling-subtree (or at the
    parent's start_offset if no prior sibling carried a span). This yields a
    zero-length anchor that's structurally sound — it sits inside the parent
    range and after any earlier sibling content.
    """
    by_id = {n["id"]: n for n in nodes}
    children: dict[str, list[tuple[int, str]]] = {}
    for e in edges:
        if e.get("type") != "child":
            continue
        children.setdefault(e["src"], []).append(
            (e["payload"]["index"], e["dst"])
        )
    for k in children:
        children[k].sort(key=lambda p: p[0])

    fallback_root = {
        "start_offset": 0,
        "end_offset": 0,
        "start_line": None,
        "end_line": None,
        "start_col": None,
        "end_col": None,
    }
    if root_span is None and by_id[root_id].get("span") is None:
        by_id[root_id]["span"] = dict(fallback_root)

    def fix(nid: str, parent_start: int) -> None:
        node = by_id[nid]
        # Determine an anchor for any empty child spans encountered.
        cursor = (
            node["span"]["start_offset"]
            if node["span"] is not None
            else parent_start
        )
        own_start = cursor
        for _idx, cid in children.get(nid, []):
            child = by_id[cid]
            if child["span"] is None:
                child["span"] = {
                    "start_offset": cursor,
                    "end_offset": cursor,
                    "start_line": None,
                    "end_line": None,
                    "start_col": None,
                    "end_col": None,
                }
            fix(cid, child["span"]["start_offset"])
            cursor = max(cursor, child["span"]["end_offset"])
        # If after fixing children this node still lacks a span (no children
        # provided one) it inherits the parent-derived zero-length anchor.
        if node["span"] is None:
            node["span"] = {
                "start_offset": own_start,
                "end_offset": own_start,
                "start_line": None,
                "end_line": None,
                "start_col": None,
                "end_col": None,
            }

    fix(root_id, by_id[root_id]["span"]["start_offset"]
        if by_id[root_id].get("span") is not None else 0)
