"""Partial-promotion fix: ANSI ports must carry a queryable `direction`.

Before this fix, `ImplicitAnsiPortSyntax` ports (the common `input logic clk`
form) promoted to role="port" with NO direction — direction lived only in
structural child tokens, so the semantic query surface could not answer "list
the output ports" (eval case C8, the documented surface gap).

This pins: (1) direction lifted onto `semantic.attributes.direction`, and
(2) a typed `has_port` walk can filter on it.
"""

from __future__ import annotations

from pathlib import Path

from research.ast_experiment.src.build import build_kg
from research.ast_experiment.src.semantic import find_by_name, neighbors

CORPUS = sorted((Path(__file__).resolve().parents[1].parent / "corpus").glob("*.sv"))


def _direction(graph, path):
    n = find_by_name(graph, path)
    return n.get("semantic", {}).get("attributes", {}).get("direction")


def test_ansi_port_direction_lifted():
    graph, _, _ = build_kg(CORPUS)
    for p in ("fifo.clk", "fifo.rst_n", "fifo.push", "fifo.pop", "fifo.din"):
        assert _direction(graph, p) == "input", p
    for p in ("fifo.dout", "fifo.full", "fifo.empty"):
        assert _direction(graph, p) == "output", p


def test_output_ports_queryable_via_walk():
    """The exact traversal eval C8 needs: filter ports by direction attribute.

    Typed walk: from module `fifo`, follow `has_port` and keep ports whose
    lifted `direction` attribute is `output`.
    """
    graph, _, _ = build_kg(CORPUS)
    fifo = find_by_name(graph, "fifo")
    ports = neighbors(graph, fifo["id"], edge_type="has_port", direction="out")
    outs = {
        p["semantic"]["name"]
        for p in ports
        if p.get("semantic", {}).get("attributes", {}).get("direction") == "output"
    }
    assert outs == {"dout", "full", "empty", "status"}
