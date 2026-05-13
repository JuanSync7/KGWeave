"""Render the pyslang semantic graph via KGWeave's NetworkXBackend + export_html.

Bridges the experiment graph (plain dicts from semantic.py) into the existing
KGWeave visualization pipeline (Sigma.js HTML, same view the OpenTitan AES
demo uses).

Mapping:
  semantic node type   -> KGWeave Entity.type
  --------------------    ---------------------
  module               -> RTL_Module
  instance             -> Instance
  port                 -> Port            (port_direction set from payload)
  param                -> Parameter
  net                  -> Net
  continuous_assign    -> ContinuousAssign
  procedural_block     -> ProceduralBlock

  semantic edge type   -> KGWeave Triple.predicate (kept verbatim)
  ------------------      ---------------------------
  has_port / has_param / has_net / drives / reads / sensitive_to
  instantiates / of_module / connects

Output: research/ast_experiment/render/kgweave_graph.html

Run:  uv run python research/ast_experiment/scripts/render_kgweave.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend  # noqa: E402
from kgweave.knowledge_graph.common.schemas import Entity, Triple  # noqa: E402
from kgweave.knowledge_graph.export import export_html  # noqa: E402

from research.ast_experiment.src.build import build_kg  # noqa: E402
from research.ast_experiment.src.semantic import queryable_nodes  # noqa: E402

OUT_HTML = HERE / "render" / "kgweave_graph.html"
OUT_HTML.parent.mkdir(exist_ok=True)

_ROLE_MAP = {
    "module": "RTL_Module",
    "instance": "Instance",
    "port": "Port",
    "param": "Parameter",
    "net": "Net",
    "continuous_assign": "ContinuousAssign",
    "procedural_block": "ProceduralBlock",
    # AST-class fallbacks for nodes that became queryable but where the
    # semantic envelope didn't pick a high-level role:
    "ContinuousAssignSyntax": "ContinuousAssign",
    "ProceduralBlockSyntax": "ProceduralBlock",
    "ModuleDeclarationSyntax": "RTL_Module",
    "HierarchicalInstanceSyntax": "Instance",
    "ImplicitAnsiPortSyntax": "Port",
    "DeclaratorSyntax": "Net",
    "IdentifierSelectNameSyntax": "Selector",
    "InvocationExpressionSyntax": "Invocation",
}


def _build_semantic_graph():
    # Production multi-file path: each SV file is its own SyntaxTree, lifted
    # and promoted into one shared graph (file-stem id prefixes keep node
    # ids unique; the shared semantic_name_index lets cross-tree references
    # like top.u_fifo --of_module--> fifo resolve correctly).
    graph, _trees, _comp = build_kg([
        HERE / "fifo_pkg.sv", HERE / "fifo_if.sv",
        HERE / "fifo.sv", HERE / "fifo_asserts.sv", HERE / "top.sv",
        HERE / "cls_corpus.sv",
        HERE / "checker_corpus.sv",
    ])
    return graph


def _semantic_view(graph):
    qids = {n["id"] for n in queryable_nodes(graph)}
    kept_edges = {
        "has_port", "has_param", "has_net",
        "drives", "reads", "sensitive_to",
        "instantiates", "of_module", "connects",
    }
    nodes = [n for n in graph["nodes"] if n["id"] in qids]
    edges = [
        e for e in graph["edges"]
        if e["src"] in qids and e["dst"] in qids and e.get("type") in kept_edges
    ]
    return nodes, edges


def _to_kgweave(nodes, edges):
    """Map semantic-graph nodes/edges to KGWeave Entity/Triple objects.

    The semantic-layer node stores high-level role in ``node['semantic']['role']``
    (e.g. ``"module"``, ``"port"``, ``"net"``); the path-keyed id lives in
    ``node['semantic']['path']``. Edges in ``edges`` already reference the
    path keys, so we use ``path`` as the canonical Entity name.
    """
    entities: list[Entity] = []
    triples: list[Triple] = []
    seen: set[str] = set()
    id_to_name: dict[str, str] = {}
    for n in nodes:
        sem = n.get("semantic") or {}
        role = sem.get("role")
        path = sem.get("path") or n["id"]
        id_to_name[n["id"]] = path
        if path in seen:
            continue
        seen.add(path)
        kg_type = _ROLE_MAP.get(role) or _ROLE_MAP.get(n.get("type", ""), "Unknown")
        direction = sem.get("direction")
        sv_src = "fifo.sv" if path.startswith("fifo") else "top.sv" if path.startswith("top") else "ast_experiment"
        entities.append(
            Entity(
                name=path,
                type=kg_type,
                sources=[sv_src],
                extractor_source=["pyslang_ast_experiment"],
                layer="pyslang",
                port_direction=direction
                if kg_type == "Port" and direction in {"input", "output", "inout"}
                else None,
                attributes={
                    "semantic_role": role or "",
                    "ast_class": n.get("type", ""),
                },
            )
        )
    for e in edges:
        s = id_to_name.get(e["src"], e["src"])
        d = id_to_name.get(e["dst"], e["dst"])
        triples.append(
            Triple(
                subject=s,
                predicate=e["type"],
                object=d,
                source="ast_experiment",
                extractor_source="pyslang_ast_experiment",
                layer="pyslang",
            )
        )
    return entities, triples


def main() -> int:
    graph = _build_semantic_graph()
    nodes, edges = _semantic_view(graph)
    entities, triples = _to_kgweave(nodes, edges)

    backend = NetworkXBackend()
    backend.upsert_entities(entities)
    backend.upsert_triples(triples)

    include_types = sorted(set(_ROLE_MAP.values()))
    n = export_html(
        backend=backend,
        output_path=str(OUT_HTML),
        include_types=include_types,
        include_layers="all",
    )
    print(f"entities={len(entities)} triples={len(triples)} rendered={n}")
    print(f"wrote {OUT_HTML}")
    print(f"open: file://{OUT_HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
