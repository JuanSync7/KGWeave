"""Generate rules — S12: loop/if/case generate + elaborated blocks; S38: genvar.

Owns the pyslang.SyntaxKind set for SystemVerilog generate constructs:

* LoopGenerate
* GenerateBlock
* IfGenerate
* CaseGenerate
* GenerateRegion
* GenvarDeclaration
"""

from __future__ import annotations

import pyslang

from ..common.graph import _add_edge, _has_edge, _mark
from ..common.tokens import (
    _cls,
    _is_token,
    _token_kind_name,
)
from ..common.walk import _descendants


def rule_s12(graph, node, gid, gnode, scope, name_index, leaks,
             scope_path="", module_gid=None, **_):
    """S12: LoopGenerateSyntax + elaborated GenerateBlockSyntax instances."""
    label = None
    for d in _descendants(node):
        if _cls(d) != "GenerateBlockSyntax":
            continue
        saw_colon = False
        for tok2 in _descendants(d):
            if _is_token(tok2) and _token_kind_name(tok2) == "Colon":
                saw_colon = True
                continue
            if saw_colon and _is_token(tok2) and _token_kind_name(tok2) == "Identifier":
                label = tok2.valueText
                break
        break
    if scope is None or label is None:
        anon_path = f"{scope_path}.<unlabeled>" if scope_path else "<unlabeled>"
        _mark(gnode, role="generate_loop", name=label or "<unlabeled>",
              path=anon_path, label=label)
        return
    gen_array = None
    try:
        for sym in scope:
            if (type(sym).__name__ == "GenerateBlockArraySymbol"
                    and getattr(sym, "name", "") == label):
                gen_array = sym
                break
    except Exception:
        gen_array = None
    if gen_array is None:
        loop_path = f"{scope_path}.{label}" if scope_path else label
        _mark(gnode, role="generate_loop", name=label, path=loop_path, label=label)
        return
    try:
        entries = list(gen_array.entries)
    except Exception:
        entries = []
    loop_path = f"{scope_path}.{label}" if scope_path else label
    _mark(gnode, role="generate_loop", name=label, path=loop_path,
          label=label, iter_count=len(entries))
    name_index[loop_path] = gid
    if module_gid is not None and not _has_edge(graph, module_gid, gid, "has_generate"):
        _add_edge(graph, module_gid, gid, "has_generate")
    nodes_list_local = graph["nodes"]
    for i, blk in enumerate(entries):
        blk_path = getattr(blk, "hierarchicalPath", "") or f"{scope_path}.{label}[{i}]"
        if blk_path.startswith("$root."):
            blk_path = blk_path[len("$root."):]
        blk_id = f"gen:{blk_path}"
        nodes_list_local.append({
            "id": blk_id,
            "type": "GenerateBlockSyntax",
            "kind": "GenerateBlock",
            "is_token": False,
            "payload": {"synthetic": True, "iteration": i},
            "queryable": True,
            "semantic": {"role": "generate_block",
                         "name": f"{label}[{i}]",
                         "path": blk_path},
        })
        _add_edge(graph, gid, blk_id, "contains_block")
        name_index[blk_path] = blk_id
        for sub in blk:
            if type(sub).__name__ != "InstanceSymbol":
                continue
            inst_name = getattr(sub, "name", "")
            inst_path = getattr(sub, "hierarchicalPath", "") or f"{blk_path}.{inst_name}"
            if inst_path.startswith("$root."):
                inst_path = inst_path[len("$root."):]
            def_name = sub.body.name if getattr(sub, "body", None) else ""
            inst_id = f"gen:{inst_path}"
            nodes_list_local.append({
                "id": inst_id,
                "type": "HierarchicalInstanceSyntax",
                "kind": "HierarchicalInstance",
                "is_token": False,
                "payload": {"synthetic": True},
                "queryable": True,
                "semantic": {"role": "instance", "name": inst_name,
                             "path": inst_path, "of_module": def_name},
            })
            name_index[inst_path] = inst_id
            _add_edge(graph, blk_id, inst_id, "instantiates")
            def_id = (name_index.get("module:" + def_name)
                      or name_index.get("interface:" + def_name)
                      or name_index.get(def_name))
            if def_id is not None:
                _add_edge(graph, inst_id, def_id, "of_module")


def _s12_generate_block(*args, **kwargs):
    return


def _s12_if_generate(*args, **kwargs):
    return


def _s12_case_generate(*args, **kwargs):
    return


def _s12_generate_region(*args, **kwargs):
    return


def rule_s38(*args, **kwargs):
    """S38: GenvarDeclaration — promoted in pass-1 of the walker.

    A single ``genvar i, j, k;`` declaration may carry multiple identifiers.
    Pass-1 in ``dispatch.promote`` fans each identifier out to its own
    queryable node (canonical node for the first, synthetic nodes for the
    rest) and emits a ``has_genvar`` edge from the enclosing module to each.
    This stub exists as an ownership marker for the BUCKET_1_CHECKLIST; it
    has no runtime effect at the pass-2 dispatch site.
    """
    return


rule_s12.__rule_id__ = "S12a"
_s12_generate_block.__rule_id__ = "S12b"
_s12_if_generate.__rule_id__ = "S12c"
_s12_case_generate.__rule_id__ = "S12c"
_s12_generate_region.__rule_id__ = "S12c"
rule_s38.__rule_id__ = "S38"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.LoopGenerate, rule_s12),
    (pyslang.SyntaxKind.GenerateBlock, _s12_generate_block),
    (pyslang.SyntaxKind.IfGenerate, _s12_if_generate),
    (pyslang.SyntaxKind.CaseGenerate, _s12_case_generate),
    (pyslang.SyntaxKind.GenerateRegion, _s12_generate_region),
    (pyslang.SyntaxKind.GenvarDeclaration, rule_s38),
]
