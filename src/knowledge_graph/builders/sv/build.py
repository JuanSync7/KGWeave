"""Generic multi-file knowledge-graph builder.

``build_kg(sv_paths)`` is the production entry point: each SystemVerilog
file becomes its own ``pyslang.SyntaxTree``, all trees are absorbed by ONE
``pyslang.Compilation``, and they are lifted+promoted into ONE shared graph
dict. Node ids are namespaced by file-path stem so the structural ids stay
unique across files; the semantic name_index is shared so cross-file
references (e.g. ``top.u_fifo --of_module--> fifo``) resolve correctly.

No string concatenation of source files: the production multi-file path
must reflect how RTL tooling actually consumes SV (per-file SyntaxTrees).

v1.2-#1 added a per-file lift cache; v1.3-#1 layers a per-file ``promote()``
cache on top of it (see :mod:`.semantic.promote_cache` for the soundness
argument). Both caches live in-process — there is no on-disk persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyslang

from .lift import _sha256_hex, lift_file_cached
from .semantic.promote_cache import (
    compute_corpus_fp,
    compute_ruleset_fp,
    promote_file_cached,
)


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
    node_counts: list[int] = []
    file_uris: list[str] = []
    file_shas: list[str] = []
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
        #
        # v1.2-#1: per-file lift cache. ``lift_file_cached`` parses the
        # SyntaxTree fresh every call (Compilation needs each tree present
        # to resolve cross-file references) but skips the lift recursion
        # for files whose ``(uri, sha256, id_prefix)`` match a prior call.
        file_bytes = path_obj.read_bytes()
        uri = str(path_obj.resolve())
        sha = _sha256_hex(file_bytes)
        nodes_before = len(graph["nodes"])
        offsets.append(nodes_before)
        tree, _root_id = lift_file_cached(
            file_bytes=file_bytes,
            graph=graph,
            id_prefix=prefix,
            uri=uri,
            sha=sha,
        )
        node_counts.append(len(graph["nodes"]) - nodes_before)
        compilation.addSyntaxTree(tree)
        trees.append(tree)
        prefixes.append(prefix)
        file_uris.append(uri)
        file_shas.append(sha)

    # v1.3-#1: compute the corpus fingerprint once. It pins every cached
    # per-file promote delta to the exact set of files that produced it —
    # cross-file edges (of_module, references_interface, declares, …)
    # resolve through name_index whose values are gids that embed the
    # producing file's stem-prefix + counter, so any change to any file's
    # content invalidates every cached delta. See promote_cache module
    # docstring for the soundness argument.
    corpus_fp = compute_corpus_fp(list(zip(file_uris, file_shas)))
    ruleset_fp = compute_ruleset_fp()

    # Phase 2: run S1 (pass1) across EVERY tree so the shared
    # semantic_name_index is fully populated before any tree's S6 looks up
    # ``module:<name>`` for a cross-file instantiation.
    for tree, off, uri, sha, count in zip(
        trees, offsets, file_uris, file_shas, node_counts
    ):
        promote_file_cached(
            graph, tree, compilation,
            node_offset=off, phase="pass1",
            uri=uri, sha=sha,
            corpus_fp=corpus_fp, ruleset_fp=ruleset_fp,
            tree_node_count=count,
        )

    # Phase 3: run S2..S6 (pass2) across every tree. S6 can now resolve
    # cross-file ``of_module`` targets because pass1 already promoted them.
    for tree, off, uri, sha, count in zip(
        trees, offsets, file_uris, file_shas, node_counts
    ):
        promote_file_cached(
            graph, tree, compilation,
            node_offset=off, phase="pass2",
            uri=uri, sha=sha,
            corpus_fp=corpus_fp, ruleset_fp=ruleset_fp,
            tree_node_count=count,
        )

    return graph, trees, compilation
