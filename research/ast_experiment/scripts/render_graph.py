"""Compile fifo.sv + top.sv into the semantic graph and render three views.

Outputs in research/ast_experiment/render/:
  graph.txt      — textual summary (nodes by type, edges by type)
  graph.dot      — Graphviz DOT (for `dot -Tsvg graph.dot -o graph.svg`)
  graph.md       — Markdown with an embedded Mermaid diagram (renders in GitHub)

Only the *queryable* (semantic) layer is rendered. The structural backbone is
huge (one node per Syntax node, hundreds of leaves) and not useful to look at;
the queryable layer is what an agent or human would actually walk.

Run:  uv run python research/ast_experiment/scripts/render_graph.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent.parent))

import pyslang  # noqa: E402

from research.ast_experiment.scripts.lift import lift  # noqa: E402
from research.ast_experiment.scripts.semantic import (  # noqa: E402
    promote,
    queryable_nodes,
)

OUT = HERE / "render"
OUT.mkdir(exist_ok=True)


def _build():
    fifo = pyslang.SyntaxTree.fromText((HERE / "fifo.sv").read_text())
    top = pyslang.SyntaxTree.fromText((HERE / "top.sv").read_text())
    compilation = pyslang.Compilation()
    compilation.addSyntaxTree(fifo)
    compilation.addSyntaxTree(top)
    graph_fifo = lift(fifo)
    graph_top = lift(top)
    # Merge both lifted graphs into one semantic graph for rendering.
    merged = {
        "nodes": graph_fifo["nodes"] + graph_top["nodes"],
        "edges": graph_fifo.get("edges", []) + graph_top.get("edges", []),
    }
    # The promote() pipeline runs per syntax tree against the shared compilation.
    promote(graph_fifo, fifo, compilation)
    promote(graph_top, top, compilation)
    # Re-merge after promotion so semantic edges/flags are unified.
    merged = {
        "nodes": graph_fifo["nodes"] + graph_top["nodes"],
        "edges": graph_fifo.get("edges", []) + graph_top.get("edges", []),
    }
    return merged


def _semantic_subset(graph):
    qids = {n["id"] for n in queryable_nodes(graph)}
    nodes = [n for n in graph["nodes"] if n["id"] in qids]
    edges = [
        e
        for e in graph["edges"]
        if e["src"] in qids and e["dst"] in qids and e.get("type") in {
            "has_port", "has_param", "has_net",
            "drives", "reads", "sensitive_to",
            "instantiates", "of_module", "connects",
        }
    ]
    return nodes, edges


def _text(nodes, edges) -> str:
    by_type = defaultdict(list)
    for n in nodes:
        by_type[n.get("type", "?")].append(n)
    lines = ["# Semantic-layer graph (queryable view)", ""]
    lines.append(f"Nodes: {len(nodes)}  Edges: {len(edges)}")
    lines.append("")
    lines.append("## Nodes by type")
    for t, ns in sorted(by_type.items()):
        lines.append(f"  {t} ({len(ns)})")
        for n in sorted(ns, key=lambda x: x.get("name", "")):
            extra = ""
            attrs = n.get("attrs", {}) or {}
            if attrs.get("direction"):
                extra = f"  [{attrs['direction']}]"
            lines.append(f"    {n['id']}{extra}")
    lines.append("")
    lines.append("## Edges by type")
    edges_by_type = defaultdict(list)
    for e in edges:
        edges_by_type[e["type"]].append(e)
    for t, es in sorted(edges_by_type.items()):
        lines.append(f"  {t} ({len(es)})")
        for e in es:
            pl = ""
            p = e.get("payload") or {}
            if t == "sensitive_to" and "edge" in p:
                pl = f"  [{p['edge']}]"
            if t == "connects" and "port" in p:
                pl = f"  [port={p['port']}]"
            lines.append(f"    {e['src']}  -->  {e['dst']}{pl}")
    return "\n".join(lines) + "\n"


def _dot(nodes, edges) -> str:
    color = {
        "module": "lightblue",
        "instance": "lightyellow",
        "port": "lightgreen",
        "param": "lightpink",
        "net": "lightgray",
        "continuous_assign": "wheat",
        "procedural_block": "khaki",
    }
    etype_color = {
        "drives": "darkgreen",
        "reads": "blue",
        "sensitive_to": "purple",
        "instantiates": "red",
        "of_module": "red",
        "connects": "orange",
        "has_port": "gray",
        "has_param": "gray",
        "has_net": "gray",
    }
    lines = ["digraph SV {", '  rankdir=LR;', '  node [shape=box, style=filled, fontsize=10];']
    for n in nodes:
        t = n.get("type", "?")
        c = color.get(t, "white")
        label = f"{n.get('name', n['id'])}\\n[{t}]"
        lines.append(f'  "{n["id"]}" [label="{label}", fillcolor="{c}"];')
    for e in edges:
        c = etype_color.get(e["type"], "black")
        p = e.get("payload") or {}
        lbl = e["type"]
        if e["type"] == "sensitive_to" and "edge" in p:
            lbl = f"{e['type']}\\n{p['edge']}"
        if e["type"] == "connects" and "port" in p:
            lbl = f"{e['type']}\\n.{p['port']}"
        lines.append(f'  "{e["src"]}" -> "{e["dst"]}" [label="{lbl}", color="{c}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _safe_id(s: str) -> str:
    return s.replace(".", "_").replace("-", "_")


def _mermaid(nodes, edges) -> str:
    """Mermaid flowchart. Groups nodes by enclosing module/instance for legibility."""
    lines = ["```mermaid", "flowchart LR"]
    # Group by top-level prefix (module name)
    by_owner = defaultdict(list)
    for n in nodes:
        nid = n["id"]
        owner = nid.split(".")[0] if "." in nid else nid
        by_owner[owner].append(n)
    for owner, ns in by_owner.items():
        lines.append(f"  subgraph {_safe_id(owner)}[\"{owner}\"]")
        for n in ns:
            shape_l, shape_r = {
                "module": ("([", "])"),
                "instance": ("[[", "]]"),
                "port": ("([", "])"),
                "param": ("[/", "/]"),
                "net": ("[", "]"),
                "continuous_assign": ("{{", "}}"),
                "procedural_block": ("{{", "}}"),
            }.get(n.get("type", ""), ("[", "]"))
            label = n.get("name", n["id"]).replace('"', "'")
            lines.append(f"    {_safe_id(n['id'])}{shape_l}\"{label}\"{shape_r}")
        lines.append("  end")
    for e in edges:
        et = e["type"]
        p = e.get("payload") or {}
        lbl = et
        if et == "sensitive_to" and "edge" in p:
            lbl = f"{et} {p['edge']}"
        if et == "connects" and "port" in p:
            lbl = f"{et} .{p['port']}"
        lines.append(f"  {_safe_id(e['src'])} -- \"{lbl}\" --> {_safe_id(e['dst'])}")
    lines.append("```")
    return "\n".join(lines) + "\n"


def main() -> int:
    graph = _build()
    nodes, edges = _semantic_subset(graph)

    (OUT / "graph.txt").write_text(_text(nodes, edges))
    (OUT / "graph.dot").write_text(_dot(nodes, edges))
    md = "# Semantic graph — fifo.sv + top.sv\n\n"
    md += f"Nodes: {len(nodes)}, edges: {len(edges)}.\n\n"
    md += _mermaid(nodes, edges)
    (OUT / "graph.md").write_text(md)

    print(f"wrote {OUT}/graph.txt    ({(OUT/'graph.txt').stat().st_size} bytes)")
    print(f"wrote {OUT}/graph.dot    ({(OUT/'graph.dot').stat().st_size} bytes)")
    print(f"wrote {OUT}/graph.md     ({(OUT/'graph.md').stat().st_size} bytes)")
    print(f"nodes={len(nodes)} edges={len(edges)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
