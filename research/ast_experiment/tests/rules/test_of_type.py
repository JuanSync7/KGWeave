"""Partial-promotion fix: a signal typed by a user-defined type gets an
`of_type` edge to that type's node.

Before this, a port like `output fifo_status_e status` promoted to role="port"
with no link to the `fifo_status_e` typedef — "what type is this signal?" needed
the structural blob. This increment covers the PORT case (type lives in the
port header); nets/params (type is a declarator sibling) are a follow-up.
"""

from __future__ import annotations

from pathlib import Path

from research.ast_experiment.src.build import build_kg
from research.ast_experiment.src.semantic import find_by_name, neighbors

CORPUS = sorted((Path(__file__).resolve().parents[1].parent / "corpus").glob("*.sv"))


def test_typed_port_links_to_typedef():
    graph, _, _ = build_kg(CORPUS)
    status = find_by_name(graph, "fifo.status")
    types = neighbors(graph, status["id"], edge_type="of_type")
    paths = {t["semantic"].get("path") for t in types}
    assert paths == {"fifo_pkg.fifo_status_e"}, paths


def test_builtin_typed_port_has_no_of_type():
    """A `logic` port (built-in keyword type, no NamedType) gets no of_type."""
    graph, _, _ = build_kg(CORPUS)
    clk = find_by_name(graph, "fifo.clk")
    assert neighbors(graph, clk["id"], edge_type="of_type") == []


def test_of_type_queryable_via_walk():
    graph, _, _ = build_kg(CORPUS)
    status = find_by_name(graph, "fifo.status")
    res = sorted(
        t["semantic"]["path"]
        for t in neighbors(graph, status["id"], edge_type="of_type", direction="out")
    )
    assert res == ["fifo_pkg.fifo_status_e"]


# ---- nets / params: type is a declarator *sibling* (parent lookup) ----

def _of_type_paths(graph, path):
    n = find_by_name(graph, path)
    return {t["semantic"].get("path")
            for t in neighbors(graph, n["id"], edge_type="of_type")}


def test_typed_net_links_to_typedef():
    graph, _, _ = build_kg(CORPUS)
    assert _of_type_paths(graph, "of_type_demo.cur_status") == {"fifo_pkg.fifo_status_e"}


def test_shared_type_links_each_declarator():
    """`fifo_word_t cur_word, prev_word;` — both declarators link to the type."""
    graph, _, _ = build_kg(CORPUS)
    assert _of_type_paths(graph, "of_type_demo.cur_word") == {"fifo_pkg.fifo_word_t"}
    assert _of_type_paths(graph, "of_type_demo.prev_word") == {"fifo_pkg.fifo_word_t"}


def test_typed_param_links_to_typedef():
    graph, _, _ = build_kg(CORPUS)
    assert _of_type_paths(graph, "of_type_demo.INIT_ST") == {"fifo_pkg.fifo_status_e"}


def test_builtin_typed_net_has_no_of_type():
    """`logic [7:0] plain_net;` — built-in type, no NamedType, no of_type."""
    graph, _, _ = build_kg(CORPUS)
    assert _of_type_paths(graph, "of_type_demo.plain_net") == set()


def test_net_of_type_queryable_via_walk():
    graph, _, _ = build_kg(CORPUS)
    cur_word = find_by_name(graph, "of_type_demo.cur_word")
    res = sorted(
        t["semantic"]["path"]
        for t in neighbors(graph, cur_word["id"], edge_type="of_type", direction="out")
    )
    assert res == ["fifo_pkg.fifo_word_t"]


# ---- ScopedName (`pkg::T`): type is the LAST segment, no import ----

def test_scoped_type_net_links_to_typedef():
    """`fifo_pkg::fifo_status_e scoped_status;` (no import) → the TYPE, not pkg."""
    graph, _, _ = build_kg(CORPUS)
    assert _of_type_paths(graph, "scoped_type_demo.scoped_status") == {"fifo_pkg.fifo_status_e"}


def test_scoped_type_param_links_to_typedef():
    graph, _, _ = build_kg(CORPUS)
    assert _of_type_paths(graph, "scoped_type_demo.SCOPED_INIT") == {"fifo_pkg.fifo_status_e"}


def test_scoped_type_does_not_link_to_package():
    """Regression: must resolve the last segment (the type), never grab the
    leading package segment as if it were the type."""
    graph, _, _ = build_kg(CORPUS)
    n = find_by_name(graph, "scoped_type_demo.scoped_status")
    targets = neighbors(graph, n["id"], edge_type="of_type")
    roles = {t.get("semantic", {}).get("role") for t in targets}
    assert "package" not in roles, roles
    assert all(not str(t["id"]).startswith("_unresolved") for t in targets)
