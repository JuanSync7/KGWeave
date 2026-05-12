"""Generic typed pattern walker — the 20% escape hatch."""

from __future__ import annotations

from typing import Any, Iterator


def queryable_nodes(graph: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for n in graph["nodes"]:
        if n.get("queryable"):
            yield n


def graph_query(graph: dict[str, Any], pattern: dict[str, Any]) -> list[Any]:
    """Tiny typed pattern walker over the graph.

    See the module docstring on the legacy ``scripts.semantic`` for the
    pattern shape. Semantics: ``match`` selects the start frontier; each
    ``follow`` step is one typed BFS hop with optional node and
    edge-payload filters; the final frontier is projected via ``return``
    (default ``"node"``). All matching is exact-equality over typed
    attributes — no regex, no substring scans.
    """
    nodes = graph["nodes"]
    by_id = {n["id"]: n for n in nodes}

    def _node_matches(n: dict[str, Any], pred: dict[str, Any]) -> bool:
        for k, v in pred.items():
            if k == "type":
                if n.get("type") != v:
                    return False
            elif k in {"role", "name", "path"}:
                if n.get("semantic", {}).get(k) != v:
                    return False
            elif k == "payload":
                payload = n.get("payload", {})
                if not isinstance(payload, dict):
                    return False
                for pk, pv in v.items():
                    if payload.get(pk) != pv:
                        return False
            elif k == "queryable":
                if bool(n.get("queryable")) != bool(v):
                    return False
            elif k == "payload_edge":
                continue
            else:
                if n.get(k) != v:
                    return False
        return True

    def _edge_payload_matches(edge: dict[str, Any], pred: dict[str, Any]) -> bool:
        ep = edge.get("payload", {}) or {}
        for k, v in pred.items():
            if ep.get(k) != v:
                return False
        return True

    match_pred = pattern.get("match", {}) or {}
    frontier: list[str] = [n["id"] for n in nodes if _node_matches(n, match_pred)]

    for step in pattern.get("follow", []) or []:
        edge_type = step.get("edge")
        direction = step.get("direction", "out")
        node_filter_raw = step.get("filter", {}) or {}
        edge_payload_pred = (
            node_filter_raw.get("payload_edge")
            if isinstance(node_filter_raw, dict) else None
        )
        node_filter = {k: v for k, v in node_filter_raw.items() if k != "payload_edge"}
        next_frontier: list[str] = []
        frontier_set = set(frontier)
        for e in graph["edges"]:
            if edge_type is not None and e["type"] != edge_type:
                continue
            if edge_payload_pred is not None and not _edge_payload_matches(e, edge_payload_pred):
                continue
            if direction == "out":
                if e["src"] not in frontier_set:
                    continue
                dst = by_id.get(e["dst"])
                if dst is None:
                    continue
                if _node_matches(dst, node_filter):
                    next_frontier.append(dst["id"])
            elif direction == "in":
                if e["dst"] not in frontier_set:
                    continue
                src = by_id.get(e["src"])
                if src is None:
                    continue
                if _node_matches(src, node_filter):
                    next_frontier.append(src["id"])
        frontier = next_frontier

    projection = pattern.get("return", "node")
    if projection == "id":
        return sorted(set(frontier))
    if projection == "name":
        return sorted({by_id[i].get("semantic", {}).get("name")
                       for i in frontier
                       if by_id[i].get("semantic", {}).get("name") is not None})
    if projection == "path":
        return sorted({by_id[i].get("semantic", {}).get("path")
                       for i in frontier
                       if by_id[i].get("semantic", {}).get("path") is not None})
    seen_ids: set[str] = set()
    out: list[dict[str, Any]] = []
    for i in frontier:
        if i in seen_ids:
            continue
        seen_ids.add(i)
        out.append(by_id[i])
    return out
