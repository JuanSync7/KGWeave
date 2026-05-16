"""SA4 acceptance: query engine ground truth.

The JS query engine in ``demo/web/query.js`` and this Python port both
interpret ``demo/data/queries.json`` identically. This test is the spec —
it loads ``graph.json`` + ``queries.json`` and asserts the exact node /
edge counts (and, for the path query, the exact node-id sequence) each
canned query must return.

If the JS engine diverges from these numbers, the FE animation will
mismatch the inspector text — that's the contract.

The free-form DSL parser is covered by two unit tests at the bottom.
"""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

import pytest

EXPERIMENT = Path(__file__).resolve().parents[2]
DATA = EXPERIMENT / "demo" / "data"
GRAPH_JSON = DATA / "graph.json"
QUERIES_JSON = DATA / "queries.json"
QUERY_JS = EXPERIMENT / "demo" / "web" / "query.js"


# ---------------------------------------------------------------------------
# Python port of the JS query engine — the source of truth.
# ---------------------------------------------------------------------------


def _match_filter(node: dict, flt: dict) -> bool:
    sem = node.get("semantic") or {}
    for k, v in flt.items():
        if k == "role_in":
            if sem.get("role") not in v:
                return False
        elif k == "role":
            if sem.get("role") != v:
                return False
        elif k == "name":
            if sem.get("name") != v:
                return False
        elif k == "path":
            if sem.get("path") != v:
                return False
        elif k == "file":
            sp = node.get("span") or {}
            if sp.get("file") != v:
                return False
        elif k == "kind":
            kind = (node.get("kind") or "").replace("SyntaxKind.", "").replace("TokenKind.", "")
            if kind != v:
                return False
        elif k == "id":
            if node.get("id") != v:
                return False
        else:
            return False
    return True


def _find_anchors(graph: dict, flt: dict) -> list[dict]:
    return [n for n in graph["nodes"] if _match_filter(n, flt)]


def _build_adj(graph: dict) -> tuple[dict, dict]:
    inc: dict[str, list[dict]] = {}
    out: dict[str, list[dict]] = {}
    for e in graph["edges"]:
        out.setdefault(e["src"], []).append(e)
        inc.setdefault(e["dst"], []).append(e)
    return inc, out


def _bfs(seeds: list[str], adj: dict, via: list[str], depth: int, key: str) -> tuple[set, set]:
    """BFS using `key`='src' (reverse) or 'dst' (forward) to choose neighbour."""
    visited_n = set(seeds)
    visited_e: set[str] = set()
    frontier = list(seeds)
    for _ in range(depth):
        nxt: list[str] = []
        for nid in frontier:
            for e in adj.get(nid, []):
                if e["type"] not in via:
                    continue
                visited_e.add(e["id"])
                neighbour = e[key]
                if neighbour not in visited_n:
                    visited_n.add(neighbour)
                    nxt.append(neighbour)
        frontier = nxt
    return visited_n, visited_e


def _find_path(src_id: str, dst_id: str, out_adj: dict, via: list[str], depth: int):
    q = deque([(src_id, [src_id], [])])
    seen = {src_id}
    while q:
        nid, npath, epath = q.popleft()
        if nid == dst_id:
            return npath, epath
        if len(npath) - 1 >= depth:
            continue
        for e in out_adj.get(nid, []):
            if e["type"] not in via:
                continue
            if e["dst"] in seen:
                continue
            seen.add(e["dst"])
            q.append((e["dst"], npath + [e["dst"]], epath + [e["id"]]))
    return None, None


def run_canned(graph: dict, spec: dict) -> dict:
    inc, out = _build_adj(graph)
    kind = spec["kind"]
    if kind == "filter":
        ns = [n["id"] for n in graph["nodes"] if _match_filter(n, spec["filter"])]
        return {"nodes": ns, "edges": []}
    if kind == "reverse_traverse":
        anchors = _find_anchors(graph, spec["anchor"])
        seeds = [a["id"] for a in anchors]
        nset, eset = _bfs(seeds, inc, spec["via"], spec["depth"], "src")
        return {"nodes": sorted(nset), "edges": sorted(eset)}
    if kind == "multi_anchor_traverse":
        anchors = _find_anchors(graph, spec["anchor"])
        seeds = [a["id"] for a in anchors]
        nset, eset = _bfs(seeds, out, spec["via"], spec["depth"], "dst")
        return {"nodes": sorted(nset), "edges": sorted(eset)}
    if kind == "path":
        srcs = _find_anchors(graph, spec["from"])
        dsts = _find_anchors(graph, spec["to"])
        if not srcs or not dsts:
            return {"nodes": [], "edges": [], "paths": []}
        np_, ep_ = _find_path(srcs[0]["id"], dsts[0]["id"], out, spec["via"], spec["depth"])
        if np_ is None:
            return {"nodes": [], "edges": [], "paths": []}
        return {"nodes": np_, "edges": ep_, "paths": [np_]}
    raise ValueError(f"unknown query kind: {kind}")


# ---------------------------------------------------------------------------
# Free-form DSL parser (Python port — JS mirrors).
# Grammar (one-line):
#   <term>*  where term ∈
#     key=value         filter
#     from=<nodeId>     traversal seed
#     via=<type>[,<type>]*   edge whitelist
#     depth=<int>       BFS depth
#     direction=fwd|rev BFS direction (default fwd)
# ---------------------------------------------------------------------------


def parse_freeform(query_str: str) -> dict:
    out: dict = {"filters": {}, "from": None, "via": None, "depth": 1, "direction": "fwd"}
    if not query_str or not query_str.strip():
        return {"error": "empty query"}
    for tok in query_str.strip().split():
        if "=" not in tok:
            return {"error": f"bad token: {tok!r}"}
        k, v = tok.split("=", 1)
        if k == "from":
            out["from"] = v
        elif k == "via":
            out["via"] = [t for t in v.split(",") if t]
        elif k == "depth":
            try:
                out["depth"] = int(v)
            except ValueError:
                return {"error": f"depth not int: {v!r}"}
        elif k == "direction":
            if v not in ("fwd", "rev"):
                return {"error": f"direction must be fwd|rev: {v!r}"}
            out["direction"] = v
        elif k in ("role", "name", "path", "file", "kind", "id"):
            out["filters"][k] = v
        else:
            return {"error": f"unknown key: {k!r}"}
    return out


def run_freeform(graph: dict, query_str: str) -> dict:
    parsed = parse_freeform(query_str)
    if "error" in parsed:
        return parsed
    # If from+via given → traversal
    if parsed["from"] and parsed["via"]:
        inc, out_adj = _build_adj(graph)
        adj = out_adj if parsed["direction"] == "fwd" else inc
        key = "dst" if parsed["direction"] == "fwd" else "src"
        nset, eset = _bfs([parsed["from"]], adj, parsed["via"], parsed["depth"], key)
        return {"nodes": sorted(nset), "edges": sorted(eset)}
    # Else pure filter
    ns = [n["id"] for n in graph["nodes"] if _match_filter(n, parsed["filters"])]
    return {"nodes": ns, "edges": []}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def graph():
    return json.loads(GRAPH_JSON.read_text())


@pytest.fixture(scope="module")
def queries():
    return json.loads(QUERIES_JSON.read_text())


@pytest.fixture(scope="module")
def queries_by_id(queries):
    return {q["id"]: q for q in queries["queries"]}


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_queries_json_exists():
    assert QUERIES_JSON.is_file(), f"{QUERIES_JSON} missing"


def test_query_js_exists():
    assert QUERY_JS.is_file(), f"{QUERY_JS} missing"


def test_queries_json_shape(queries):
    assert queries["version"] == "1"
    assert isinstance(queries["queries"], list)
    assert len(queries["queries"]) >= 6, "must have at least 6 canned queries (SPEC §5)"
    for q in queries["queries"]:
        for f in ("id", "label", "blurb", "kind"):
            assert f in q, f"query {q.get('id')!r} missing field {f}"


# ---------------------------------------------------------------------------
# Per-canned-query tests (one per query, 7 total — 6 required + 1 bonus)
# ---------------------------------------------------------------------------


def test_q1_all_modules(graph, queries_by_id):
    """Q1: filter role=module returns exactly 25 module nodes from the corpus."""
    res = run_canned(graph, queries_by_id["q1_all_modules"])
    assert len(res["nodes"]) == 25
    assert "fifo:n0003.ModuleDeclarationSyntax" in res["nodes"]
    assert "top:n0062.ModuleDeclarationSyntax" in res["nodes"]


def test_q2_instances_of_fifo(graph, queries_by_id):
    """Q2: reverse-BFS of_module edges into module:fifo returns 5 instances + 1 anchor."""
    res = run_canned(graph, queries_by_id["q2_instances_of_fifo"])
    assert len(res["edges"]) == 5
    assert "fifo:n0003.ModuleDeclarationSyntax" in res["nodes"]
    # All matched nodes (besides anchor) are HierarchicalInstanceSyntax instances.
    by_id = {n["id"]: n for n in graph["nodes"]}
    instances = [nid for nid in res["nodes"]
                 if nid != "fifo:n0003.ModuleDeclarationSyntax"]
    assert len(instances) == 5
    for nid in instances:
        assert by_id[nid]["type"] == "HierarchicalInstanceSyntax"


def test_q3_drives_full(graph, queries_by_id):
    """Q3: reverse-BFS drives from port fifo.full returns the LHS-driver chain."""
    res = run_canned(graph, queries_by_id["q3_drives_full"])
    assert len(res["edges"]) >= 1
    by_id = {n["id"]: n for n in graph["nodes"]}
    anchor = next(n for n in graph["nodes"]
                  if (n.get("semantic") or {}).get("path") == "fifo.full")
    assert anchor["id"] in res["nodes"]
    # At least one driver is a ContinuousAssign.
    driver_ids = [nid for nid in res["nodes"] if nid != anchor["id"]]
    assert any(by_id[d]["type"] == "ContinuousAssignSyntax" for d in driver_ids)


def test_q4_sensitivity_chain_always_ff(graph, queries_by_id):
    """Q4: every always_ff procedural_block + its sensitive_to outgoing edges."""
    res = run_canned(graph, queries_by_id["q4_sensitivity_chain_always_ff"])
    # 1 always_ff in corpus + 2 sensitivity-signal targets = 3 nodes, 2 edges.
    assert len(res["edges"]) == 2
    by_id = {n["id"]: n for n in graph["nodes"]}
    aff_in_result = [nid for nid in res["nodes"]
                     if (by_id[nid].get("semantic") or {}).get("role") == "always_ff"]
    assert len(aff_in_result) == 1


def test_q5_top_to_fifo_path(graph, queries_by_id):
    """Q5: BFS path from module:top to module:fifo via {instantiates, of_module, connects}.

    Expected 2-hop path: top -instantiates-> instance -of_module-> fifo.
    """
    res = run_canned(graph, queries_by_id["q5_top_to_fifo_path"])
    assert res["paths"], "expected at least one path"
    path = res["paths"][0]
    assert len(path) == 3, f"expected 3 nodes (2 hops), got {len(path)}: {path}"
    assert path[0] == "top:n0062.ModuleDeclarationSyntax"
    assert path[-1] == "fifo:n0003.ModuleDeclarationSyntax"
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id[path[1]]["type"] == "HierarchicalInstanceSyntax"


def test_q6_all_assertions(graph, queries_by_id):
    """Q6: every node with semantic.role in {assertion, property, sequence}."""
    res = run_canned(graph, queries_by_id["q6_all_assertions"])
    assert len(res["nodes"]) == 17
    by_id = {n["id"]: n for n in graph["nodes"]}
    roles = {by_id[nid]["semantic"]["role"] for nid in res["nodes"]}
    assert roles <= {"assertion", "property", "sequence"}


def test_q7_class_extends_chain(graph, queries_by_id):
    """Q7 (bonus): every class node + outgoing extends edges (depth 2)."""
    res = run_canned(graph, queries_by_id["q7_class_extends_chain"])
    assert len(res["edges"]) == 2
    # 7 classes in the cls_corpus + no new nodes (extends targets are also classes)
    assert len(res["nodes"]) == 7


# ---------------------------------------------------------------------------
# Free-form DSL tests
# ---------------------------------------------------------------------------


def test_freeform_filter(graph):
    """DSL filter: role=module returns same 25 nodes as Q1."""
    res = run_freeform(graph, "role=module")
    assert "error" not in res
    assert len(res["nodes"]) == 25


def test_freeform_traversal(graph):
    """DSL traversal: from=<fifo> via=of_module direction=rev depth=1 finds 5 instance edges."""
    res = run_freeform(
        graph,
        "from=fifo:n0003.ModuleDeclarationSyntax via=of_module direction=rev depth=1",
    )
    assert "error" not in res
    assert len(res["edges"]) == 5


def test_freeform_error_unknown_key(graph):
    res = run_freeform(graph, "nosuch=value")
    assert "error" in res


def test_freeform_error_empty(graph):
    res = run_freeform(graph, "")
    assert "error" in res


# ---------------------------------------------------------------------------
# JS query.js syntax + structural sanity
# ---------------------------------------------------------------------------


def test_query_js_exports_required_symbols():
    """query.js exports the four documented entry points."""
    src = QUERY_JS.read_text()
    for sym in ("runCannedQuery", "parseAndRunFreeform", "animatePath", "pulseNodes"):
        assert sym in src, f"query.js missing exported symbol {sym}"


def test_query_js_node_check():
    """`node --check query.js` succeeds, if Node is available."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available for --check")
    res = subprocess.run([node, "--check", str(QUERY_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


# ---------------------------------------------------------------------------
# Perf — sanity bound, not a strict SLA.
# ---------------------------------------------------------------------------


def test_bfs_perf_under_50ms(graph):
    """Full-graph BFS over 7222 nodes / 7721 edges completes well under 50ms."""
    _, out = _build_adj(graph)
    seeds = [n["id"] for n in graph["nodes"] if (n.get("semantic") or {}).get("role") == "module"]
    t0 = time.perf_counter()
    _bfs(seeds, out, ["instantiates", "of_module", "connects", "drives", "reads", "child"], 10, "dst")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 50.0, f"BFS took {elapsed_ms:.2f}ms; expected <50ms"
