"""Connectivity queries — neighbours, named lookups, port/instance/modport
traversals. Pure typed-edge projections over a promoted graph."""

from __future__ import annotations

from typing import Any, Iterator


def queryable_nodes(graph: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield the promoted (queryable) nodes of a graph.

    A trivial generator over ``graph['nodes']`` — NOT part of the retired
    pattern-walker DSL. Relocated here from the deleted ``graph_query`` module
    so its public facade path is unchanged for render scripts and rule tests.
    """
    for n in graph["nodes"]:
        if n.get("queryable"):
            yield n


def neighbors(
    graph: dict[str, Any],
    node_id: str,
    edge_type: str | None = None,
    direction: str = "out",
) -> list[dict[str, Any]]:
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[dict[str, Any]] = []
    for e in graph["edges"]:
        if edge_type is not None and e["type"] != edge_type:
            continue
        if direction == "out" and e["src"] == node_id:
            out.append(by_id[e["dst"]])
        elif direction == "in" and e["dst"] == node_id:
            out.append(by_id[e["src"]])
    return out


def find_by_name(graph: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Look up a promoted node by hierarchical path or bare leaf name."""
    idx = graph.get("semantic_name_index", {})
    nid = idx.get(name)
    if nid is None:
        suffix = "." + name
        candidates = [v for k, v in idx.items() if k == name or k.endswith(suffix)]
        if len(candidates) == 1:
            nid = candidates[0]
    if nid is None:
        return None
    by_id = {n["id"]: n for n in graph["nodes"]}
    return by_id[nid]


def instances_of(graph: dict[str, Any], module_name: str) -> list[str]:
    by_id = {n["id"]: n for n in graph["nodes"]}
    idx = graph.get("semantic_name_index", {})
    mod_id = idx.get("module:" + module_name) or idx.get(module_name)
    if mod_id is None:
        return []
    out: list[str] = []
    for e in graph["edges"]:
        if e["type"] != "of_module" or e["dst"] != mod_id:
            continue
        src = by_id.get(e["src"])
        if src is None:
            continue
        path = src.get("semantic", {}).get("path")
        if path:
            out.append(path)
    return sorted(out)


def port_connections(graph: dict[str, Any], instance_path: str) -> list[dict[str, Any]]:
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[dict[str, Any]] = []
    for e in graph["edges"]:
        if e["type"] != "connects":
            continue
        if e["payload"].get("instance") != instance_path:
            continue
        src = by_id.get(e["src"])
        if src is None:
            continue
        src_path = src.get("semantic", {}).get("path") or src.get("semantic", {}).get("name")
        out.append({"port": e["payload"].get("port"), "src_path": src_path})
    return out


def modports_of(graph: dict[str, Any], interface_name: str) -> list[str]:
    iface = find_by_name(graph, interface_name)
    if iface is None:
        return []
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[str] = []
    for e in graph["edges"]:
        if e["type"] != "has_modport" or e["src"] != iface["id"]:
            continue
        dst = by_id.get(e["dst"])
        if dst is None:
            continue
        nm = dst.get("semantic", {}).get("name")
        if nm:
            out.append(nm)
    return sorted(out)


def package_of(graph: dict[str, Any], typedef_path: str) -> str | None:
    td = find_by_name(graph, typedef_path)
    if td is None:
        return None
    by_id = {n["id"]: n for n in graph["nodes"]}
    for e in graph["edges"]:
        if e["type"] != "has_typedef" or e["dst"] != td["id"]:
            continue
        owner = by_id.get(e["src"])
        if owner is None:
            continue
        return owner.get("semantic", {}).get("name")
    return None


def param_overrides(graph: dict[str, Any], instance_path: str) -> dict[str, str]:
    inst = find_by_name(graph, instance_path)
    if inst is None:
        return {}
    out: dict[str, str] = {}
    for e in graph["edges"]:
        if e["type"] != "param_override" or e["src"] != inst["id"]:
            continue
        name = e["payload"].get("name")
        value = e["payload"].get("value")
        if name is not None:
            out[name] = value
    return out
