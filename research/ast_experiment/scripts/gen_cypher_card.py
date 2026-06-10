"""Generate docs/card_cypher.md from the LIVE vocabulary of the built graph.

Usage::

    uv run python research/ast_experiment/scripts/gen_cypher_card.py

The card is the one teaching artifact handed to an LLM for Cypher traversal of
the SV knowledge graph. It MUST be generated from the live graph — never
hand-authored — so a drift test can catch stale content.

Public functions used by the test::

    live_edges(graph) -> list[str]   — sorted edge-type names (child excluded)
    live_roles(graph) -> list[str]   — sorted role names from queryable nodes
    generate_card(graph) -> str      — full card markdown text (deterministic)

NO timestamps, NO dict-iteration order dependence. Two runs → byte-identical.
NO ``import re`` / ``from re`` anywhere in this module.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public derivation functions — imported by the test for bidirectional check
# ---------------------------------------------------------------------------

def live_edges(graph: dict[str, Any]) -> list[str]:
    """Return sorted list of semantic edge types present in graph.

    Mirrors _EDGE_TYPES from _kuzu_load.py: excludes 'child', non-promoted
    sources/targets, and non-identifier edge names.
    """
    node_ids = {n["id"] for n in graph["nodes"] if n.get("queryable")}

    def _ident(t: str) -> bool:
        return t.isidentifier()

    types = sorted({
        e["type"]
        for e in graph["edges"]
        if e["type"] != "child"
        and e["src"] in node_ids
        and e["dst"] in node_ids
        and _ident(e["type"])
    })
    return types


def live_roles(graph: dict[str, Any]) -> list[str]:
    """Return sorted list of role names from queryable nodes."""
    roles = sorted({
        n["semantic"]["role"]
        for n in graph["nodes"]
        if n.get("queryable") and n.get("semantic", {}).get("role")
    })
    return roles


# ---------------------------------------------------------------------------
# Card generation — DETERMINISTIC (no timestamps, sorted everywhere)
# ---------------------------------------------------------------------------

# The five S1 recipe query shapes, verbatim
_RECIPES = [
    (
        "Methods of class `cls_pkg.data_xact`?",
        "MATCH (c:N)-[:has_method]->(m:N) WHERE c.path='cls_pkg.data_xact' RETURN m.name",
    ),
    (
        "Ports OR nets of interface `fifo_if`?",
        "MATCH (i:N)-[:has_port|has_net]->(s:N) WHERE i.name='fifo_if' RETURN s.name",
    ),
    (
        "Each instance in `top` and its module?",
        "MATCH (t:N)-[:instantiates]->(i:N)-[:of_module]->(m:N) WHERE t.name='top' RETURN i.path, m.name",
    ),
    (
        "How many ports does `fifo` have?",
        "MATCH (f:N)-[:has_port]->(p:N) WHERE f.name='fifo' RETURN count(p)",
    ),
    (
        "Signals that feed what drives `fifo.full`?",
        "MATCH (f:N)<-[:drives]-(d:N)-[:reads]->(s:N) WHERE f.path='fifo.full' RETURN DISTINCT s.name",
    ),
]


def _fmt_backtick_list(items: list[str]) -> str:
    """Format a sorted list as a comma-separated backtick-quoted string."""
    return ", ".join(f"`{x}`" for x in sorted(items))


def generate_card(graph: dict[str, Any]) -> str:
    """Generate and return the full card markdown text.

    Deterministic: given the same graph, always produces byte-identical output.
    """
    edges = live_edges(graph)
    roles = live_roles(graph)

    # Partition edges: has_* (containment) vs others (relationship)
    containment = sorted(e for e in edges if e.startswith("has_"))
    relationship = sorted(e for e in edges if not e.startswith("has_"))

    # Partition roles by family (order matches reference card)
    _design_units = {"module", "interface", "program", "package", "class",
                     "checker", "primitive_instance"}
    _ports_signals = {"port", "net", "param", "net_decl", "nettype",
                      "user_defined_net_decl", "port_reference", "port_concat",
                      "genvar", "local_var", "type_param"}
    _behavioral = {"procedural_block", "continuous_assign", "function",
                   "function_prototype", "function_port", "method",
                   "method_prototype", "system_call", "identifier_select",
                   "event_trigger", "procedural_assign", "procedural_force",
                   "procedural_deassign", "procedural_release", "always",
                   "always_comb", "always_ff"}
    _hierarchy = {"instance", "generate_loop", "generate_block"}
    _types = {"typedef", "typedef_forward", "enum_value", "struct_member",
              "union_member"}
    _verification = {"assertion", "assertion_item_port", "property", "sequence",
                     "let_decl", "default_disable", "covergroup", "coverpoint",
                     "cross", "coverage_bins", "constraint",
                     "inline_constraint_block"}
    _iface_plumbing = {"modport", "interface_port", "clocking", "clocking_item"}
    _externs = {"extern_decl", "extern_udp", "dpi_import"}

    role_set = set(roles)

    def _pick(family: set[str]) -> list[str]:
        return sorted(role_set & family)

    def _other(assigned: set[str]) -> list[str]:
        return sorted(role_set - assigned)

    all_assigned = (
        _design_units | _ports_signals | _behavioral | _hierarchy | _types
        | _verification | _iface_plumbing | _externs
    )
    other_roles = _other(all_assigned)

    families = [
        ("Design units / scopes", _pick(_design_units)),
        ("Ports & signals", _pick(_ports_signals)),
        ("Behavioral logic", _pick(_behavioral)),
        ("Hierarchy", _pick(_hierarchy)),
        ("Types", _pick(_types)),
        ("Verification", _pick(_verification)),
        ("Interface plumbing", _pick(_iface_plumbing)),
        ("Externs / DPI", _pick(_externs)),
    ]
    if other_roles:
        families.append(("Other", other_roles))

    # Count totals for the intro blurb
    role_count = len(roles)
    edge_count = len(edges)

    lines: list[str] = []

    # ---- Header ----
    lines += [
        "# SV Graph Schema Card — Cypher surface",
        "",
        "The one-page contract for traversing the SystemVerilog knowledge graph **with",
        "Cypher** and getting accurate answers without grep. The graph is loaded into an",
        "embedded property-graph DB; you query it with standard Cypher. Everything here is",
        "measured from the live graph over the corpus, not aspirational.",
        "",
        f"> The graph has **{role_count} node roles** and **{edge_count} semantic"
        f" relationship types**.",
        "",
        "---",
        "",
    ]

    # ---- Schema section ----
    lines += [
        "## Schema (what to MATCH on)",
        "",
        "There is **one node label**, `N`, with these properties:",
        "",
        "| property | meaning |",
        "|---|---|",
        "| `id` | opaque unique id (rarely needed) |",
        "| `role` | the node's kind — see Roles section |",
        "| `name` | bare identifier (`count`, `fifo`) |",
        "| `path` | hierarchical identity (`fifo.count`, `top.u_fifo`) — **the key you usually match on** |",
        "| `direction` | for ports/modport items: `\"input\"`/`\"output\"`/`\"inout\"` (else null) |",
        "",
        "Relationships are **typed** — the relationship type IS the semantic edge name",
        "(`-[:reads]->`, `-[:has_method]->`, `-[:of_module]->`). See Edges section.",
        "",
        "Node-valued returns (e.g. `RETURN s`) are hydrated to",
        "`SemanticNode{id, role, name, path, attributes}` — the full nested attributes dict",
        "is restored from the graph by node id (not the flattened kuzu row).",
        "",
        "Standard Cypher applies: `WHERE`, `IN`, `NOT`, `count()/collect()`, multiple",
        "`RETURN` columns, variable-length `-[:reads*1..3]->`, `DISTINCT`, etc.",
        "",
        "---",
        "",
    ]

    # ---- Roles section ----
    lines += [
        "## Roles",
        "",
        f"There are **{role_count} node roles**. Match with `{{role:'…'}}` or"
        " `WHERE n.role IN [...]`.",
        "",
        "| Family | Roles |",
        "|---|---|",
    ]
    for family_name, family_roles in families:
        if family_roles:
            lines.append(f"| **{family_name}** | {_fmt_backtick_list(family_roles)} |")
    lines += ["", "---", ""]

    # ---- Edges section ----
    lines += [
        "## Edges",
        "",
        f"There are **{edge_count} semantic relationship types**.",
        "Structural `child` edges are NOT loaded; unresolved-target edges are skipped.",
        "",
        "### Containment — scope X owns member Y (`has_*`)",
        "",
        _fmt_backtick_list(containment) + ".",
        "",
        "The child's `role` tells you what kind of member it is. To get several kinds at",
        "once, union the types or filter on role:",
        "`MATCH (i:N {name:'fifo_if'})-[:has_port|has_net]->(s:N) RETURN s.name`.",
        "",
        "### Relationship edges",
        "",
    ]

    # Sub-group relationship edges
    _dataflow = {"drives", "reads", "checks", "connects", "sensitive_to",
                 "triggers", "aliases", "groups_net", "groups_port_ref"}
    _hier_res = {"instantiates", "of_module", "of_checker", "of_type", "calls",
                 "extends", "implements", "imports", "imports_item",
                 "exports_all", "references_interface", "prototypes", "declares",
                 "bind_target", "bound_into"}
    _misc = {"param_override", "defparam_override", "default_clocking",
             "dpi_exports", "contains_block"}

    rel_set = set(relationship)
    dataflow = sorted(rel_set & _dataflow)
    hier_res = sorted(rel_set & _hier_res)
    misc = sorted(rel_set - _dataflow - _hier_res)

    if dataflow:
        lines += [
            "**Dataflow** — how values move:",
            "",
            _fmt_backtick_list(dataflow) + ".",
            "",
        ]
    if hier_res:
        lines += [
            "**Hierarchy & resolution** — how names bind:",
            "",
            _fmt_backtick_list(hier_res) + ".",
            "",
        ]
    if misc:
        lines += [
            "**Overrides & misc:**",
            "",
            _fmt_backtick_list(misc) + ".",
            "",
        ]

    lines += ["---", ""]

    # ---- Conventions section ----
    lines += [
        "## Conventions",
        "",
        "- `path` is identity: always prefer matching on `path` over bare `name`",
        "  when you know the hierarchical location (`fifo.full`, not `full`).",
        "- Name-vs-path projection: both `RETURN n.name` and `RETURN n.path` are valid;",
        "  choose whichever granularity the question demands.",
        "- Unresolved targets (forward/external refs) have no node row — a relationship",
        "  to them simply matches nothing.",
        "- For complex traversals like transitive fan-in (alternating `signal<-[:drives]-",
        "  assign-[:reads]->signal` chains), use a `saved_query` (available in a later",
        "  slice) rather than raw Cypher, which has no clean recursive form.",
        "",
        "---",
        "",
    ]

    # ---- Recipes section ----
    lines += [
        "## Recipes",
        "",
        "Runnable Cypher examples against the corpus. Each executes without error.",
        "",
    ]
    for question, cypher in _RECIPES:
        lines += [
            f"**{question}**",
            "",
            "```cypher",
            cypher,
            "```",
            "",
        ]

    lines += ["---", ""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point — write docs/card_cypher.md
# ---------------------------------------------------------------------------

def main() -> None:
    root = Path(__file__).resolve().parents[1]

    # Ensure repo root is on sys.path so imports resolve in both script mode
    # (uv run python …) and pytest (which adds cwd automatically).
    _repo_root = str(root.parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    corpus = sorted((root / "corpus").glob("*.sv"))

    from research.ast_experiment.src.build import build_kg  # noqa: PLC0415

    g, _, _ = build_kg(corpus)
    card_text = generate_card(g)

    out_path = root / "docs" / "card_cypher.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(card_text, encoding="utf-8")
    print(f"Written: {out_path}  ({len(card_text)} bytes, {len(card_text.splitlines())} lines)")


if __name__ == "__main__":
    main()
