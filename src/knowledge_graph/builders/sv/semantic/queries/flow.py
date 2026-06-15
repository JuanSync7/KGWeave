"""Data-flow queries: drivers, fan-in cone, fan-out cone."""

from __future__ import annotations

from typing import Any

from .connectivity import find_by_name, neighbors


def find_drivers(graph: dict[str, Any], name: str) -> list[dict[str, Any]]:
    target = find_by_name(graph, name)
    if target is None:
        return []
    return neighbors(graph, target["id"], edge_type="drives", direction="in")


def reads_of(graph: dict[str, Any], name: str) -> list[dict[str, Any]]:
    target = find_by_name(graph, name)
    if target is None:
        return []
    return neighbors(graph, target["id"], edge_type="reads", direction="in")


def cone_of_influence(graph: dict[str, Any], name: str) -> set[str]:
    """Backward reachability."""
    target = find_by_name(graph, name)
    if target is None:
        return set()
    seen: set[str] = set()
    frontier = [target["id"]]
    while frontier:
        nxt: list[str] = []
        for nid in frontier:
            if nid in seen:
                continue
            seen.add(nid)
            for driver in neighbors(graph, nid, edge_type="drives", direction="in"):
                if driver["id"] not in seen:
                    nxt.append(driver["id"])
                for r in neighbors(graph, driver["id"], edge_type="reads", direction="out"):
                    if r["id"] not in seen:
                        nxt.append(r["id"])
            for parent in neighbors(graph, nid, edge_type="connects", direction="in"):
                if parent["id"] not in seen:
                    nxt.append(parent["id"])
        frontier = nxt
    return seen


def forward_cone(graph: dict[str, Any], name: str) -> set[str]:
    """Forward reachability — symmetric counterpart to cone_of_influence."""
    target = find_by_name(graph, name)
    if target is None:
        return set()
    seen: set[str] = set()
    frontier = [target["id"]]
    while frontier:
        nxt: list[str] = []
        for nid in frontier:
            if nid in seen:
                continue
            seen.add(nid)
            for reader in neighbors(graph, nid, edge_type="reads", direction="in"):
                if reader["id"] not in seen:
                    nxt.append(reader["id"])
                for d in neighbors(graph, reader["id"], edge_type="drives", direction="out"):
                    if d["id"] not in seen:
                        nxt.append(d["id"])
            for connected in neighbors(graph, nid, edge_type="connects", direction="out"):
                if connected["id"] not in seen:
                    nxt.append(connected["id"])
            for connected in neighbors(graph, nid, edge_type="connects", direction="in"):
                if connected["id"] not in seen:
                    nxt.append(connected["id"])
        frontier = nxt
    return seen
