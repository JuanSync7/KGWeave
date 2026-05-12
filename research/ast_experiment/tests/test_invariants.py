"""Structural invariants for the multi-file SV knowledge graph.

These are properties of the graph **as a graph** — independent of any
particular query. Each invariant would have caught the cross-tree merge bug
where lifting per tree and merging dicts dropped ``of_module`` edges and
collided on per-tree node ids.

Run against the production multi-file path ``build_kg([FIFO, TOP])`` so the
asserts only fire when the real production path is broken.
"""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
PKG = HERE / "fifo_pkg.sv"
IFACE = HERE / "fifo_if.sv"
FIFO = HERE / "fifo.sv"
TOP = HERE / "top.sv"
TB = HERE / "tb_fifo.sv"


_CONTAINMENT_EDGES = {
    "has_port", "has_param", "has_net", "contains", "instantiates",
    "has_typedef", "has_enum_value", "has_modport", "has_function",
    "has_generate", "contains_block",
}
_SEMANTIC_EDGES = {
    "drives", "reads", "sensitive_to",
    "connects", "instantiates", "of_module",
}
_CONTAINED_ROLES = {
    "port", "param", "net", "instance", "typedef", "enum_value",
    "modport", "function", "generate_loop", "generate_block",
}
# Roles whose `name` is treated as an owning namespace (top-level container).
_OWNER_ROLES = {"module", "package", "interface"}


@pytest.fixture(scope="module")
def kg():
    from scripts.build import build_kg

    graph, trees, comp = build_kg([PKG, IFACE, FIFO, TOP, TB])
    return graph, trees, comp


@pytest.fixture(scope="module")
def graph(kg):
    return kg[0]


def _queryable(graph):
    from scripts.semantic import queryable_nodes

    return list(queryable_nodes(graph))


def _id_to_node(graph):
    return {n["id"]: n for n in graph["nodes"]}


def _role(n):
    return n.get("semantic", {}).get("role")


def _path(n):
    return n.get("semantic", {}).get("path") or n.get("semantic", {}).get("name") or n["id"]


# ---------------------------------------------------------------------------
# 1. Containment connectivity.
# ---------------------------------------------------------------------------


def test_inv1_containment_connectivity(graph):
    """Every contained queryable node (port/param/net/instance) is reachable
    from at least one module node via has_port/has_param/has_net/contains.

    Catches: a module's port/net appearing disconnected because the cross-file
    merge dropped its containing module."""
    modules = {n["id"] for n in _queryable(graph) if _role(n) in _OWNER_ROLES}
    assert modules, "no module/package nodes promoted"

    # BFS from every module/package along containment edges.
    reachable: set[str] = set(modules)
    frontier = list(modules)
    while frontier:
        nxt = []
        fset = set(frontier)
        for e in graph["edges"]:
            if e["type"] not in _CONTAINMENT_EDGES:
                continue
            if e["src"] in fset and e["dst"] not in reachable:
                reachable.add(e["dst"])
                nxt.append(e["dst"])
        frontier = nxt

    orphans = [
        _path(n) for n in _queryable(graph)
        if _role(n) in _CONTAINED_ROLES and n["id"] not in reachable
    ]
    assert not orphans, (
        f"queryable nodes not reachable from any module via containment edges: {orphans}"
    )


# ---------------------------------------------------------------------------
# 2. Instance closure.
# ---------------------------------------------------------------------------


def test_inv2_instance_closure(graph):
    """Every queryable instance has exactly one outbound of_module edge AND
    exactly one inbound instantiates edge.

    Catches: the cross-file merge dropping top.u_fifo --of_module--> fifo."""
    insts = [n for n in _queryable(graph) if _role(n) == "instance"]
    assert insts, "no instance nodes in the multi-file graph"
    bad = []
    for inst in insts:
        nid = inst["id"]
        of_out = [e for e in graph["edges"] if e["type"] == "of_module" and e["src"] == nid]
        inst_in = [e for e in graph["edges"] if e["type"] == "instantiates" and e["dst"] == nid]
        if len(of_out) != 1 or len(inst_in) != 1:
            bad.append(
                f"{_path(inst)}: of_module(out)={len(of_out)}, instantiates(in)={len(inst_in)}"
            )
    assert not bad, "instance closure broken: " + "; ".join(bad)


# ---------------------------------------------------------------------------
# 3. Port containment.
# ---------------------------------------------------------------------------


def test_inv3_port_containment(graph):
    """Every queryable port has exactly one inbound has_port edge from a module."""
    by_id = _id_to_node(graph)
    bad = []
    for n in _queryable(graph):
        if _role(n) != "port":
            continue
        incoming = [e for e in graph["edges"]
                    if e["type"] == "has_port" and e["dst"] == n["id"]]
        if len(incoming) != 1:
            bad.append(f"{_path(n)}: has_port(in)={len(incoming)}")
            continue
        owner = by_id.get(incoming[0]["src"])
        if owner is None or _role(owner) not in _OWNER_ROLES:
            bad.append(f"{_path(n)}: has_port src is not a module/interface")
    assert not bad, "port containment broken: " + "; ".join(bad)


# ---------------------------------------------------------------------------
# 4. Param containment.
# ---------------------------------------------------------------------------


def test_inv4_param_containment(graph):
    """Every queryable param has exactly one inbound has_param edge from a module."""
    by_id = _id_to_node(graph)
    bad = []
    for n in _queryable(graph):
        if _role(n) != "param":
            continue
        incoming = [e for e in graph["edges"]
                    if e["type"] == "has_param" and e["dst"] == n["id"]]
        if len(incoming) != 1:
            bad.append(f"{_path(n)}: has_param(in)={len(incoming)}")
            continue
        owner = by_id.get(incoming[0]["src"])
        if owner is None or _role(owner) not in _OWNER_ROLES:
            bad.append(f"{_path(n)}: has_param src is not a module/package")
    assert not bad, "param containment broken: " + "; ".join(bad)


# ---------------------------------------------------------------------------
# 5. Connects endpoints.
# ---------------------------------------------------------------------------


def test_inv5_connects_endpoints(graph):
    """Every ``connects`` edge has both endpoints queryable; src is a parent
    net/port and dst is a child port whose owning module differs from src's."""
    by_id = _id_to_node(graph)
    qids = {n["id"] for n in _queryable(graph)}
    bad = []
    for e in graph["edges"]:
        if e["type"] != "connects":
            continue
        if e["src"] not in qids or e["dst"] not in qids:
            bad.append(f"non-queryable endpoint: {e['src']} -> {e['dst']}")
            continue
        dst = by_id[e["dst"]]
        if _role(dst) != "port":
            bad.append(f"dst not a port: {_path(dst)} role={_role(dst)}")
            continue
        src = by_id[e["src"]]
        # Owning module = first dotted component of the hierarchical path.
        src_path = _path(src)
        dst_path = _path(dst)
        src_mod = src_path.split(".", 1)[0] if "." in src_path else src_path
        dst_mod = dst_path.split(".", 1)[0] if "." in dst_path else dst_path
        if src_mod == dst_mod:
            bad.append(
                f"connects within same module: {src_path} -> {dst_path} (both under {src_mod})"
            )
    assert not bad, "connects-endpoint invariant broken: " + "; ".join(bad)


# ---------------------------------------------------------------------------
# 6. Hierarchical-path consistency.
# ---------------------------------------------------------------------------


def test_inv6_hierarchical_path_consistency(graph):
    """Every contained queryable node id's semantic.path starts with its
    owning module name as the first dotted component (e.g. ``fifo.count``,
    ``top.u_fifo``).

    Catches: per-tree id collisions silently aliasing nodes from different
    modules to the same path."""
    by_id = _id_to_node(graph)
    # Build owner module for each contained node.
    bad = []
    # For each containment edge, derive the owner.
    owner: dict[str, str] = {}
    for e in graph["edges"]:
        if e["type"] not in _CONTAINMENT_EDGES:
            continue
        owner_node = by_id.get(e["src"])
        if owner_node is None or _role(owner_node) not in _OWNER_ROLES:
            continue
        owner[e["dst"]] = owner_node["semantic"]["name"]
    # Also instance parents via 'instantiates' for the instance node itself.
    for e in graph["edges"]:
        if e["type"] != "instantiates":
            continue
        owner_node = by_id.get(e["src"])
        if owner_node is None or _role(owner_node) not in _OWNER_ROLES:
            continue
        owner.setdefault(e["dst"], owner_node["semantic"]["name"])
    # Enum values' "owner" is their typedef, which itself sits under a
    # package/module. Project the enum-value owner up to that container so
    # the path-prefix check stays "first dotted component == container".
    for e in graph["edges"]:
        if e["type"] != "has_enum_value":
            continue
        td_node = by_id.get(e["src"])
        if td_node is None or _role(td_node) != "typedef":
            continue
        td_owner = owner.get(td_node["id"])
        if td_owner is not None:
            owner.setdefault(e["dst"], td_owner)
    # Generated instances flow ownership through generate_loop → generate_block
    # → instance. Walk the chain until every contained node has the original
    # module owner stamped.
    for _ in range(4):
        for e in graph["edges"]:
            if e["type"] not in _CONTAINMENT_EDGES:
                continue
            src_owner = owner.get(e["src"])
            if src_owner is None:
                continue
            owner.setdefault(e["dst"], src_owner)

    for n in _queryable(graph):
        if _role(n) not in _CONTAINED_ROLES:
            continue
        path = n.get("semantic", {}).get("path")
        if path is None:
            bad.append(f"{n['id']}: missing semantic.path for role={_role(n)}")
            continue
        # Synthetic elaborated nodes (id prefix ``gen:``) carry full
        # elaborated hierarchical paths, whose first dotted component is the
        # top-of-hierarchy instance name (e.g. ``tb_fifo.u_dut.gen_fifos[0]``).
        # The cross-tree-collision threat the invariant guards against does
        # not apply to these synthetic nodes — their ids are namespaced by the
        # elaborated path string itself. Skip them.
        if n["id"].startswith("gen:"):
            continue
        owner_mod = owner.get(n["id"])
        if owner_mod is None:
            bad.append(f"{path}: no owning module (no containment edge)")
            continue
        first = path.split(".", 1)[0]
        if first != owner_mod:
            bad.append(f"{path}: path prefix {first!r} != owner module {owner_mod!r}")
    assert not bad, "hierarchical-path consistency broken: " + "; ".join(bad)


# ---------------------------------------------------------------------------
# 7. No orphan semantic edges.
# ---------------------------------------------------------------------------


def test_inv7_no_orphan_semantic_edges(graph):
    """Every typed semantic edge's endpoints are queryable nodes.

    Catches: cross-tree edges that point at node ids belonging to a different
    tree's namespace (the literal lift-collision symptom)."""
    qids = {n["id"] for n in _queryable(graph)}
    bad = []
    for e in graph["edges"]:
        if e["type"] not in _SEMANTIC_EDGES:
            continue
        if e["src"] not in qids:
            bad.append(f"{e['type']}: src {e['src']} not queryable")
        if e["dst"] not in qids:
            bad.append(f"{e['type']}: dst {e['dst']} not queryable")
    assert not bad, "orphan semantic edges: " + "; ".join(bad[:10])


# ---------------------------------------------------------------------------
# 8. Param-override target is a param on the instance's of_module side.
# ---------------------------------------------------------------------------


def test_inv8_param_override_target_is_param(graph):
    """Every ``param_override`` edge runs from an instance node to a ``param``
    node owned by the instance's ``of_module``. Catches: overrides resolved
    against the wrong module, or routed to a non-param node."""
    by_id = _id_to_node(graph)
    bad = []
    for e in graph["edges"]:
        if e["type"] != "param_override":
            continue
        src = by_id.get(e["src"])
        dst = by_id.get(e["dst"])
        if src is None or _role(src) != "instance":
            bad.append(f"src not instance: {e['src']}")
            continue
        if dst is None or _role(dst) != "param":
            bad.append(f"dst not param: {e['dst']} role={_role(dst) if dst else None}")
            continue
        of_mod = src["semantic"].get("of_module")
        dst_path = _path(dst)
        if not dst_path.startswith(of_mod + "."):
            bad.append(
                f"{_path(src)} --param_override--> {dst_path} (expected prefix {of_mod!r})"
            )
    assert not bad, "param-override target invariant broken: " + "; ".join(bad)
