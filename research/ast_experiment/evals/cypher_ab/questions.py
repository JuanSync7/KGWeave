"""The Cypher-vs-pattern-dict question set + independent ground truth.

Chosen to span the accuracy-differentiating axis (easy questions where both
surfaces tie tell us nothing). Each question records:

  * ``truth_fn(graph)`` — independent ground truth (typed API / direct walk),
    a set of answer strings; multi-column truths are pipe-joined ``a|b``.
  * ``dict_oracle`` — the correct pattern-dict plan: a ``graph_query`` pattern,
    a named-tool call, or ``None`` when the pattern-dict surface *structurally
    cannot* express it (no single edge/projection, no wrapper tool).
  * ``cypher_oracle`` — the correct Cypher, or ``None`` if not cleanly
    expressible against this graph.

The ``dict_oracle is None`` set is the pattern-dict's surface ceiling gap; the
``cypher_oracle is None`` set is Cypher's. The blind panel then measures how
close each model gets to its surface's ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from research.ast_experiment.src.semantic import (
    find_by_name, neighbors, find_drivers, cone_of_influence,
)


@dataclass
class ABQuestion:
    id: str
    question: str
    axis: str                      # what capability it probes
    truth_fn: Callable[[dict[str, Any]], frozenset[str]]
    dict_oracle: dict[str, Any] | None
    cypher_oracle: str | None
    # Extra acceptable answer sets beyond truth_fn. Used to NEUTRALISE the
    # orthogonal name-vs-path projection convention: returning the right nodes
    # by `name` or by `path` both count, so this A/B measures surface capability
    # (can the surface reach the right node set) not projection style.
    accept_fns: list[Callable[[dict[str, Any]], frozenset[str]]] | None = None

    def acceptable(self, graph) -> list[frozenset[str]]:
        return [self.truth_fn(graph)] + [f(graph) for f in (self.accept_fns or [])]


def _names(nodes) -> frozenset[str]:
    return frozenset(n["semantic"]["name"] for n in nodes
                     if n.get("semantic", {}).get("name"))


def _paths(nodes) -> frozenset[str]:
    return frozenset(n["semantic"]["path"] for n in nodes
                     if n.get("semantic", {}).get("path"))


def _paths_of_ids(g, ids) -> frozenset[str]:
    by_id = {n["id"]: n for n in g["nodes"]}
    return frozenset(by_id[i]["semantic"]["path"] for i in ids
                     if by_id.get(i, {}).get("semantic", {}).get("path"))


# ---- truth functions ----

def _t_methods(g):
    return _names(neighbors(g, find_by_name(g, "cls_pkg.data_xact")["id"],
                            edge_type="has_method"))


def _t_ports_or_nets(g):
    iface = find_by_name(g, "fifo_if")["id"]
    return (_names(neighbors(g, iface, edge_type="has_port"))
            | _names(neighbors(g, iface, edge_type="has_net")))


def _t_cone(g):
    return _paths_of_ids(g, cone_of_influence(g, "fifo.count"))


def _t_inst_module_pairs(g):
    top = find_by_name(g, "top")["id"]
    out = set()
    for inst in neighbors(g, top, edge_type="instantiates"):
        for mod in neighbors(g, inst["id"], edge_type="of_module"):
            ip = inst["semantic"].get("path"); mn = mod["semantic"].get("name")
            if ip and mn:
                out.add(f"{ip}|{mn}")
    return frozenset(out)


def _t_port_count(g):
    fifo = find_by_name(g, "fifo")["id"]
    return frozenset({str(len(neighbors(g, fifo, edge_type="has_port")))})


def _t_driver_reads_full(g):
    out = set()
    for d in find_drivers(g, "fifo.full"):
        for r in neighbors(g, d["id"], edge_type="reads"):
            if r["semantic"].get("name"):
                out.add(r["semantic"]["name"])
    return frozenset(out)


# ---- path-projection variants (same nodes, projected by path not name) ----

def _t_methods_p(g):
    return _paths(neighbors(g, find_by_name(g, "cls_pkg.data_xact")["id"],
                            edge_type="has_method"))


def _t_ports_or_nets_p(g):
    iface = find_by_name(g, "fifo_if")["id"]
    return (_paths(neighbors(g, iface, edge_type="has_port"))
            | _paths(neighbors(g, iface, edge_type="has_net")))


def _t_cone_names(g):
    by_id = {n["id"]: n for n in g["nodes"]}
    return frozenset(by_id[i]["semantic"]["name"] for i in cone_of_influence(g, "fifo.count")
                     if by_id.get(i, {}).get("semantic", {}).get("name"))


def _t_inst_module_pairs_nn(g):
    top = find_by_name(g, "top")["id"]
    out = set()
    for inst in neighbors(g, top, edge_type="instantiates"):
        for mod in neighbors(g, inst["id"], edge_type="of_module"):
            inm = inst["semantic"].get("name"); mn = mod["semantic"].get("name")
            if inm and mn:
                out.add(f"{inm}|{mn}")
    return frozenset(out)


def _t_driver_reads_full_p(g):
    out = set()
    for d in find_drivers(g, "fifo.full"):
        for r in neighbors(g, d["id"], edge_type="reads"):
            if r["semantic"].get("path"):
                out.add(r["semantic"]["path"])
    return frozenset(out)


QUESTIONS: list[ABQuestion] = [
    ABQuestion(
        id="Q1_methods", axis="containment (control — both express)",
        question="List the methods of class `cls_pkg.data_xact`.",
        truth_fn=_t_methods,
        dict_oracle={"kind": "pattern", "pattern": {
            "match": {"role": "class", "path": "cls_pkg.data_xact"},
            "follow": [{"edge": "has_method", "direction": "out"}],
            "return": "name"}},
        cypher_oracle="MATCH (c:N)-[:has_method]->(m:N) "
                      "WHERE c.path='cls_pkg.data_xact' RETURN m.name",
        accept_fns=[_t_methods_p],
    ),
    ABQuestion(
        id="Q2_ports_or_nets", axis="OR across two edges (dict gap)",
        question="List every signal of interface `fifo_if` that is either a port "
                 "or a net.",
        truth_fn=_t_ports_or_nets,
        dict_oracle=None,  # one follow = one edge type; no port|net union, no tool
        cypher_oracle="MATCH (i:N)-[:has_port|has_net]->(s:N) "
                      "WHERE i.name='fifo_if' RETURN s.name",
        accept_fns=[_t_ports_or_nets_p],
    ),
    ABQuestion(
        id="Q3_cone_of_count", axis="transitive (dict has a named tool)",
        question="List everything that can transitively affect `fifo.count` "
                 "(its full fan-in cone).",
        truth_fn=_t_cone,
        dict_oracle={"kind": "tool", "tool": "cone_of_influence",
                     "args": ["fifo.count"]},
        cypher_oracle=None,  # alternating signal<-driver->reads walk: see report
        accept_fns=[_t_cone_names],
    ),
    ABQuestion(
        id="Q4_inst_module_pairs", axis="multi-column return (dict gap)",
        question="For every instance directly in module `top`, give the pair "
                 "(instance path, the module name it is an instance of).",
        truth_fn=_t_inst_module_pairs,
        dict_oracle=None,  # graph_query projects ONE column; cannot return pairs
        cypher_oracle="MATCH (t:N)-[:instantiates]->(i:N)-[:of_module]->(m:N) "
                      "WHERE t.name='top' RETURN i.path, m.name",
        accept_fns=[_t_inst_module_pairs_nn],
    ),
    ABQuestion(
        id="Q5_port_count", axis="aggregation (dict gap)",
        question="How many ports does module `fifo` have? Answer with the count.",
        truth_fn=_t_port_count,
        dict_oracle=None,  # no aggregation, no count tool
        cypher_oracle="MATCH (f:N)-[:has_port]->(p:N) WHERE f.name='fifo' "
                      "RETURN count(p)",
    ),
    ABQuestion(
        id="Q6_driver_reads_full", axis="2-hop dataflow (control — both express)",
        question="Which signals feed the logic that drives port `fifo.full`?",
        truth_fn=_t_driver_reads_full,
        dict_oracle={"kind": "pattern", "pattern": {
            "match": {"role": "port", "path": "fifo.full"},
            "follow": [{"edge": "drives", "direction": "in"},
                       {"edge": "reads", "direction": "out"}],
            "return": "name"}},
        cypher_oracle="MATCH (f:N)<-[:drives]-(d:N)-[:reads]->(s:N) "
                      "WHERE f.path='fifo.full' RETURN DISTINCT s.name",
        accept_fns=[_t_driver_reads_full_p],
    ),
]
