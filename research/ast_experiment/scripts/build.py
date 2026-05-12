"""Generic multi-file knowledge-graph builder.

``build_kg(sv_paths)`` is the production entry point: each SystemVerilog
file becomes its own ``pyslang.SyntaxTree``, all trees are absorbed by ONE
``pyslang.Compilation``, and they are lifted+promoted into ONE shared graph
dict. Node ids are namespaced by file-path stem so the structural ids stay
unique across files; the semantic name_index is shared so cross-file
references (e.g. ``top.u_fifo --of_module--> fifo``) resolve correctly.

No string concatenation of source files: the production multi-file path
must reflect how RTL tooling actually consumes SV (per-file SyntaxTrees).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyslang

try:
    # When the experiment dir is on sys.path (pytest conftest adds it),
    # use the package-style import.
    from scripts.lift import lift
    from scripts.semantic import promote
except ImportError:  # pragma: no cover — script-mode fallback
    from .lift import lift
    from .semantic import promote


def build_kg(sv_paths: list[Path]) -> tuple[dict[str, Any], list[Any], Any]:
    """Lift + promote a list of SV files into ONE queryable graph.

    Each file is parsed as its own ``SyntaxTree`` and added to a shared
    ``Compilation``. ``lift`` is called per tree against the shared graph with
    a file-stem-derived id prefix; ``promote`` is then called per tree with the
    matching ``node_offset`` so its DFS index range maps to the correct slice
    of ``graph['nodes']``. Returns ``(graph, trees, compilation)`` — callers
    needing to round-trip an individual file can re-emit via
    ``unlift.emit_subtree(graph, root_id)`` (the per-file root is preserved
    in ``graph['order'][i]``).
    """
    graph: dict[str, Any] = {"nodes": [], "edges": [], "order": []}
    trees: list[Any] = []
    prefixes: list[str] = []
    offsets: list[int] = []
    compilation = pyslang.Compilation()
    seen_prefixes: dict[str, int] = {}

    # Phase 1: parse every file, add every SyntaxTree to the Compilation
    # BEFORE any elaboration query touches it (pyslang finalises the
    # compilation on first getRoot()/topInstances call).
    for i, p in enumerate(sv_paths):
        path_obj = Path(p)
        stem = path_obj.stem or f"file{i}"
        n = seen_prefixes.get(stem, 0)
        seen_prefixes[stem] = n + 1
        prefix = stem if n == 0 else f"{stem}{n}"
        # ``fromText`` (rather than ``fromFile``) is intentional: pyslang's
        # file-loader injects a synthetic EOF token with extra trivia that
        # diverges from ``SyntaxTree.fromText(path.read_text())`` token
        # streams — keeping the two paths uniform preserves the byte-equal
        # round-trip invariant.
        tree = pyslang.SyntaxTree.fromText(path_obj.read_text())
        compilation.addSyntaxTree(tree)
        trees.append(tree)
        prefixes.append(prefix)
        offsets.append(len(graph["nodes"]))
        lift(tree, graph=graph, id_prefix=prefix)

    # Phase 2: run S1 (pass1) across EVERY tree so the shared
    # semantic_name_index is fully populated before any tree's S6 looks up
    # ``module:<name>`` for a cross-file instantiation.
    for tree, off in zip(trees, offsets):
        promote(graph, tree, compilation, node_offset=off, phase="pass1")

    # Phase 3: run S2..S6 (pass2) across every tree. S6 can now resolve
    # cross-file ``of_module`` targets because pass1 already promoted them.
    for tree, off in zip(trees, offsets):
        promote(graph, tree, compilation, node_offset=off, phase="pass2")

    return graph, trees, compilation
