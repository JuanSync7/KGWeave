# @summary
# Backend-agnostic audit/coverage query views over a populated KG.
# Exports: audit_orphan_tests, coverage_gaps_by_target, confidence_tier_rank
# Deps: networkx (via backend.graph), no IO.
# Notable: Implements the audit-vs-test-completeness split — same graph, two
# filters, two different correct answers. Free functions, not backend methods.
# @end-summary
"""Audit and coverage query helpers over a populated knowledge graph.

These helpers operate on any storage backend that exposes a NetworkX-style
``graph`` attribute (a ``MultiDiGraph`` whose nodes carry a ``type`` and
optional ``is_test`` attribute, and whose edges carry ``confidence_tier``
and ``resolved`` attributes — as populated by Stage-1 schema and Stage-2
``SWTestExtractor``).

Two complementary views are exposed:

* :func:`audit_orphan_tests` — *precision* view. Lists real ``SW_Test``
  entities that produced no resolved ``tests_module`` edge — i.e. the
  extractor saw a test but failed to bind it to any RTL module.

* :func:`coverage_gaps_by_target` — *recall* view (with confidence floor).
  Lists nodes of a given type (default ``RTL_Module``) that have no
  inbound resolved ``tests_module`` edge meeting the confidence floor —
  i.e. modules with no test coverage at the requested confidence level.

The two views are deliberately not symmetric: an extractor that emits a
low-confidence resolved guess removes a module from the coverage-gap
list (at the ``low`` floor) but does *not* save the originating test
from the orphan list — a test with at least one resolved edge is not an
orphan regardless of tier.
"""

from __future__ import annotations

from typing import Any, Literal

__all__ = [
    "audit_orphan_tests",
    "confidence_tier_rank",
    "coverage_gaps_by_target",
    "coverage_gaps_by_target_transitive",
    "ports_by_direction",
    "trace_signal",
]


_TIER_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def confidence_tier_rank(tier: str) -> int:
    """Return the ordinal rank of ``tier``.

    ``low`` -> 0, ``medium`` -> 1, ``high`` -> 2. Anything else -> -1.
    Used by :func:`coverage_gaps_by_target` for the confidence floor
    comparison; exposed so audit reports can reuse the same ordering.
    """
    return _TIER_ORDER.get(tier, -1)


def _graph(backend: Any):
    """Return the underlying ``MultiDiGraph`` for ``backend``.

    Accepts either a backend instance with a ``.graph`` attribute or a
    raw graph (anything exposing ``nodes`` and ``edges``).
    """
    return getattr(backend, "graph", backend)


def audit_orphan_tests(backend: Any) -> list[str]:
    """Return real ``SW_Test`` nodes with no resolved ``tests_module`` edge.

    A node qualifies as an orphan iff:

    * its ``type`` is ``SW_Test``,
    * its ``is_test`` attribute is ``True`` (real test — not crt0, not
      unreadable),
    * it has zero outbound edges with ``predicate=='tests_module'`` and
      ``resolved=True``.

    Tests that have at least one resolved ``tests_module`` edge are
    excluded even if they also have unresolved (sentinel) edges.

    Returns the orphan names sorted alphabetically.
    """
    g = _graph(backend)
    orphans: list[str] = []
    for node, data in g.nodes(data=True):
        if data.get("type") != "SW_Test":
            continue
        if data.get("is_test") is not True:
            continue
        has_resolved = False
        for _u, _v, edata in g.out_edges(node, data=True):
            if (
                edata.get("relation") == "tests_module"
                or edata.get("predicate") == "tests_module"
            ) and edata.get("resolved", True) is True:
                has_resolved = True
                break
        if not has_resolved:
            orphans.append(node)
    return sorted(orphans)


def coverage_gaps_by_target(
    backend: Any,
    node_type: str = "RTL_Module",
    min_confidence: Literal["high", "medium", "low"] = "low",
) -> list[str]:
    """Return nodes of ``node_type`` with no qualifying inbound test edge.

    A node qualifies as a coverage gap iff:

    * its ``type`` equals ``node_type``,
    * it has zero inbound edges with ``predicate=='tests_module'``,
      ``resolved=True``, AND ``confidence_tier`` whose rank is at least
      ``confidence_tier_rank(min_confidence)``.

    Unresolved edges (``resolved=False`` — the ``"<unknown>"`` sentinel
    edges) NEVER count as coverage. Returned list is sorted alphabetically.
    """
    g = _graph(backend)
    floor = confidence_tier_rank(min_confidence)
    gaps: list[str] = []
    for node, data in g.nodes(data=True):
        if data.get("type") != node_type:
            continue
        covered = False
        for _u, _v, edata in g.in_edges(node, data=True):
            if (
                edata.get("relation") != "tests_module"
                and edata.get("predicate") != "tests_module"
            ):
                continue
            if edata.get("resolved", True) is not True:
                continue
            tier = edata.get("confidence_tier", "high")
            if confidence_tier_rank(tier) >= floor:
                covered = True
                break
        if not covered:
            gaps.append(node)
    return sorted(gaps)


def _edge_predicate(edata: dict) -> str | None:
    """Return the edge label, accepting either ``relation`` or ``predicate``."""
    return edata.get("relation") or edata.get("predicate")


def _directly_covered_names(g: Any, floor: int) -> set[str]:
    """Return the set of node names with a qualifying inbound tests_module edge.

    A node qualifies iff it has at least one inbound edge with predicate
    ``tests_module``, ``resolved=True``, and confidence tier rank >= ``floor``.
    """
    covered: set[str] = set()
    for u, v, edata in g.edges(data=True):
        if _edge_predicate(edata) != "tests_module":
            continue
        if edata.get("resolved", True) is not True:
            continue
        tier = edata.get("confidence_tier", "high")
        if confidence_tier_rank(tier) >= floor:
            covered.add(v)
    return covered


def coverage_gaps_by_target_transitive(
    backend: Any,
    node_type: str = "RTL_Module",
    min_confidence: Literal["high", "medium", "low"] = "low",
) -> list[str]:
    """Return alphabetical names of ``node_type`` nodes with no transitive coverage.

    A node X is *transitively covered* if X itself, or any ancestor reachable
    by walking inbound ``instantiates`` edges (i.e. parents that instantiate
    X, grandparents that instantiate those, ...) has a direct ``tests_module``
    inbound edge meeting ``min_confidence`` with ``resolved=True``.

    Cycles in ``instantiates`` are tolerated via a visited set.
    """
    g = _graph(backend)
    floor = confidence_tier_rank(min_confidence)
    directly_covered = _directly_covered_names(g, floor)

    gaps: list[str] = []
    for node, data in g.nodes(data=True):
        if data.get("type") != node_type:
            continue
        # BFS upward via inbound instantiates edges
        visited: set[str] = {node}
        stack: list[str] = [node]
        covered = False
        while stack:
            current = stack.pop()
            if current in directly_covered:
                covered = True
                break
            for u, _v, edata in g.in_edges(current, data=True):
                if _edge_predicate(edata) != "instantiates":
                    continue
                if u in visited:
                    continue
                visited.add(u)
                stack.append(u)
        if not covered:
            gaps.append(node)
    return sorted(gaps)


def trace_signal(
    backend: Any,
    source_name: str,
    max_hops: int = 50,
) -> list[list[str]]:
    """BFS over ``data_flows`` from ``source_name``.

    Walks the V2 unified ``data_flows`` predicate (which spans both
    intra-module dataflow and cross-module port-instance bindings, see
    ``docs/v2_dataflow_schema.md``) so a single BFS traces a signal
    across module boundaries without falling back to the legacy
    ``drives_signal`` / ``connects_to`` split.

    Returns a list of paths (each a list of node names from ``source_name``
    to a frontier node). Every reachable node has exactly one path entry —
    the first BFS path encountered (shortest in hop count). The source
    itself is included as a single-element path so callers can verify the
    seed reached the graph.

    Stops when the frontier is exhausted or a node would exceed ``max_hops``
    edges from the source. Cycles are tolerated via a visited set.

    Args:
        backend: Storage backend with a ``.graph`` attribute (or a raw
            ``MultiDiGraph``).
        source_name: Canonical entity name to seed the BFS.
        max_hops: Maximum edge count from source to any returned path tail.

    Returns:
        List of paths. Each path is a list of node names; the first element
        is always ``source_name``. If ``source_name`` is not in the graph,
        returns an empty list.
    """
    g = _graph(backend)
    if not g.has_node(source_name):
        return []

    paths: list[list[str]] = [[source_name]]
    visited: set[str] = {source_name}
    # BFS frontier as (node, depth, path) tuples.
    frontier: list[tuple[str, int, list[str]]] = [(source_name, 0, [source_name])]

    while frontier:
        next_frontier: list[tuple[str, int, list[str]]] = []
        for node, depth, path in frontier:
            if depth >= max_hops:
                continue
            for _u, v, edata in g.out_edges(node, data=True):
                if _edge_predicate(edata) != "data_flows":
                    continue
                if v in visited:
                    continue
                visited.add(v)
                new_path = path + [v]
                paths.append(new_path)
                next_frontier.append((v, depth + 1, new_path))
        frontier = next_frontier

    return paths


def ports_by_direction(
    backend: Any,
    module: str,
    direction: Literal["input", "output", "inout"],
) -> list[str]:
    """Return alphabetically-sorted Port names for ``module`` matching ``direction``.

    Iterates all nodes whose canonical name starts with ``f"{module}."`` and
    whose ``type`` is ``"Port"`` and whose ``port_direction`` attribute equals
    ``direction``. Returns just the local port name (the ``<module>.`` prefix
    is stripped).
    """
    g = _graph(backend)
    prefix = f"{module}."
    out: list[str] = []
    for node, data in g.nodes(data=True):
        if not isinstance(node, str) or not node.startswith(prefix):
            continue
        if data.get("type") != "Port":
            continue
        if data.get("port_direction") != direction:
            continue
        out.append(node[len(prefix):])
    return sorted(out)
