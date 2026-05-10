"""Wave-1 / track-B tests for the v2 statement-level decomposition walker.

The walker emits AST-layer nodes (`IfStatement`, `CaseStatement`, `Loop`,
`Branch`, `Assignment`, `Condition`) plus structural edges
(`then_branch`/`elif_branch`/`else_branch`, `case_item`/`default_branch`,
`condition_of`, `selector`, `case_value`, `lhs`/`rhs`, `body_of`,
`contains`).

Track A (operator/literal/cross-ref work) is parallel; this track emits
*placeholder* expression nodes (Condition / identifier-text stubs) wherever
an expression appears as a control predicate, case selector, loop bound,
case-value, or assignment LHS/RHS.

Every emitted Entity carries ``layer="ast"`` and every emitted Triple
carries ``layer="ast"`` — non-negotiable per the v2 schema doc § "Layering".
"""

from __future__ import annotations

from typing import Iterable, List

import pytest

pytest.importorskip("pyslang", reason="pyslang is a hard dep")

from kgweave.knowledge_graph.common import Entity, Triple  # noqa: E402
from kgweave.knowledge_graph.extraction.sv_dataflow_v2_statements import (  # noqa: E402
    SVStatementDecomposer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(src: str) -> tuple[List[Entity], List[Triple]]:
    dec = SVStatementDecomposer()
    res = dec.extract(text=src, source="<test>")
    return res.entities, res.triples


def _by_type(entities: Iterable[Entity], type_: str) -> List[Entity]:
    return [e for e in entities if e.type == type_]


def _by_pred(triples: Iterable[Triple], pred: str) -> List[Triple]:
    return [t for t in triples if t.predicate == pred]


def _outgoing(triples: Iterable[Triple], subj: str, pred: str) -> List[Triple]:
    return [t for t in triples if t.subject == subj and t.predicate == pred]


# ---------------------------------------------------------------------------
# Layer tagging — non-negotiable
# ---------------------------------------------------------------------------


def test_every_emitted_entity_and_triple_is_ast_layer() -> None:
    src = """
    module m_layer;
      logic a, b, c;
      always_comb begin
        if (a) c = b;
        else c = 1'b0;
      end
    endmodule
    """
    entities, triples = _run(src)
    assert entities, "expected at least one entity emitted"
    assert triples, "expected at least one triple emitted"
    for e in entities:
        assert e.layer == "ast", f"entity {e.name} ({e.type}) has layer={e.layer!r}"
    for t in triples:
        assert t.layer == "ast", (
            f"triple {t.subject} -{t.predicate}-> {t.object} has layer={t.layer!r}"
        )


# ---------------------------------------------------------------------------
# IfStatement: if / else if / else
# ---------------------------------------------------------------------------


def test_if_elif_else_emits_ordered_branches() -> None:
    src = """
    module m_if;
      logic a, b, c, d;
      always_comb begin
        if (a) c = 1'b1;
        else if (b) c = 1'b0;
        else c = d;
      end
    endmodule
    """
    entities, triples = _run(src)

    if_stmts = _by_type(entities, "IfStatement")
    branches = _by_type(entities, "Branch")
    assert len(if_stmts) == 1
    assert len(branches) == 3, (
        f"expected then + elif + else = 3 branches, got {len(branches)}"
    )

    if_id = if_stmts[0].name

    then_edges = _outgoing(triples, if_id, "then_branch")
    elif_edges = _outgoing(triples, if_id, "elif_branch")
    else_edges = _outgoing(triples, if_id, "else_branch")

    assert len(then_edges) == 1
    assert len(elif_edges) == 1
    assert len(else_edges) == 1

    # Each then/elif branch must have a Condition gating it; the else branch
    # has no condition.  Schema: Condition --condition_of--> Branch.
    cond_edges = _by_pred(triples, "condition_of")
    cond_targets = {t.object for t in cond_edges}
    branch_ids = {b.name for b in branches}
    gated_branches = cond_targets & branch_ids
    assert len(gated_branches) == 2, (
        f"expected 2 gated branches (then + elif), got {gated_branches}"
    )


def test_if_branch_path_attribute_is_set() -> None:
    """Branch nodes carry branch_path attr (encoded in aliases)."""
    src = """
    module m_bp;
      logic a, b, c;
      always_comb begin
        if (a) c = b;
      end
    endmodule
    """
    entities, _ = _run(src)
    branches = _by_type(entities, "Branch")
    assert branches
    # branch_path stored as an alias-encoded attr.  Outermost branch has empty path.
    bp = _branch_path(branches[0])
    assert bp == [], f"top-level branch_path should be empty, got {bp!r}"


def _branch_path(entity: Entity) -> List[str]:
    """Read the branch_path stored on attributes['branch_path']."""
    return list(entity.attributes.get("branch_path", []))


def test_nested_if_branch_path_orders_outermost_first() -> None:
    src = """
    module m_nested;
      logic a, b, c, d;
      always_comb begin
        if (a) begin
          if (b) c = d;
          else c = 1'b0;
        end
      end
    endmodule
    """
    entities, triples = _run(src)
    branches = _by_type(entities, "Branch")
    # Outer if -> 1 branch.  Inner if -> 2 branches (then + else).
    assert len(branches) == 3

    paths = {b.name: _branch_path(b) for b in branches}

    # Sort: branches with empty path are the outermost (1 branch).
    outer = [n for n, p in paths.items() if p == []]
    nested = [n for n, p in paths.items() if len(p) == 1]
    assert len(outer) == 1
    assert len(nested) == 2
    outer_id = outer[0]
    for nid in nested:
        assert paths[nid] == [outer_id], (
            f"nested branch_path should be [{outer_id}], got {paths[nid]}"
        )


def test_assignment_inside_branch_inherits_branch_path() -> None:
    src = """
    module m_assign_path;
      logic a, b, c, d;
      always_comb begin
        if (a) begin
          if (b) c = d;
        end
      end
    endmodule
    """
    entities, _ = _run(src)
    assigns = _by_type(entities, "Assignment")
    assert len(assigns) == 1
    bp = _branch_path(assigns[0])
    assert len(bp) == 2, (
        f"assignment in nested if should have branch_path of length 2, got {bp}"
    )


# ---------------------------------------------------------------------------
# CaseStatement: case / casex / casez / unique case
# ---------------------------------------------------------------------------


def test_case_statement_with_default_emits_branches_and_default() -> None:
    src = """
    module m_case;
      logic c, d;
      logic [1:0] s;
      always_comb begin
        case (s)
          2'b00: c = 1'b1;
          2'b01: c = 1'b0;
          default: c = d;
        endcase
      end
    endmodule
    """
    entities, triples = _run(src)
    cases = _by_type(entities, "CaseStatement")
    assert len(cases) == 1
    case_id = cases[0].name

    item_edges = _outgoing(triples, case_id, "case_item")
    default_edges = _outgoing(triples, case_id, "default_branch")
    selector_edges = _outgoing(triples, case_id, "selector")

    assert len(item_edges) == 2, (
        f"expected 2 case items, got {len(item_edges)}: {item_edges}"
    )
    assert len(default_edges) == 1
    assert len(selector_edges) == 1

    # Each non-default branch should have a case_value edge.
    case_branch_ids = {t.object for t in item_edges}
    case_value_edges = _by_pred(triples, "case_value")
    case_value_subjects = {t.subject for t in case_value_edges}
    for bid in case_branch_ids:
        assert bid in case_value_subjects, (
            f"branch {bid} missing case_value edge"
        )


@pytest.mark.parametrize("kw", ["casex", "casez", "unique case"])
def test_case_variants_recognised(kw: str) -> None:
    src = f"""
    module m_casev;
      logic c;
      logic [1:0] s;
      always_comb begin
        {kw} (s)
          2'b00: c = 1'b1;
          default: c = 1'b0;
        endcase
      end
    endmodule
    """
    entities, triples = _run(src)
    cases = _by_type(entities, "CaseStatement")
    assert len(cases) == 1
    # case_kind lives on attributes["case_kind"].
    case_kind = cases[0].attributes.get("case_kind")
    assert case_kind is not None, f"missing case_kind attribute on {cases[0]}"
    expected_substr = kw.replace(" ", "_")
    assert expected_substr in case_kind or kw.split()[0] in case_kind.lower(), (
        f"case_kind={case_kind!r} doesn't reflect '{kw}'"
    )


# ---------------------------------------------------------------------------
# Loops: for / while / repeat / forever / foreach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "loop_src, expected_kind_substr",
    [
        ("for (int i = 0; i < 4; i++) c = i;", "for"),
        ("while (a) c = 1'b0;", "while"),
        ("repeat (4) c = 1'b1;", "repeat"),
        ("forever c = 1'b0;", "forever"),
    ],
)
def test_loop_variants_emit_loop_node(loop_src: str, expected_kind_substr: str) -> None:
    src = f"""
    module m_loop;
      logic a, c;
      always_comb begin
        {loop_src}
      end
    endmodule
    """
    entities, _ = _run(src)
    loops = _by_type(entities, "Loop")
    assert len(loops) == 1, f"expected 1 Loop node, got {len(loops)}"
    # loop_kind on attributes
    loop_kind = loops[0].attributes.get("loop_kind", "")
    assert expected_kind_substr in loop_kind.lower(), (
        f"loop_kind={loop_kind!r} missing {expected_kind_substr!r}"
    )


def test_foreach_loop_emits_loop_node() -> None:
    src = """
    module m_foreach;
      logic [3:0] s;
      logic c;
      initial begin
        foreach (s[i]) c = s[i];
      end
    endmodule
    """
    entities, _ = _run(src)
    loops = _by_type(entities, "Loop")
    assert len(loops) == 1


# ---------------------------------------------------------------------------
# Assignment node: lhs / rhs / blocking vs non-blocking
# ---------------------------------------------------------------------------


def test_assignment_node_has_lhs_and_rhs_edges() -> None:
    src = """
    module m_assign;
      logic a, b, c;
      always_comb c = a & b;
    endmodule
    """
    entities, triples = _run(src)
    assigns = _by_type(entities, "Assignment")
    assert len(assigns) == 1
    aid = assigns[0].name
    lhs = _outgoing(triples, aid, "lhs")
    rhs = _outgoing(triples, aid, "rhs")
    assert len(lhs) == 1
    assert len(rhs) == 1


def test_blocking_vs_nonblocking_assign_kind() -> None:
    src = """
    module m_kinds;
      logic clk, a, b, c, d;
      always_ff @(posedge clk) c <= a;
      always_comb d = b;
      assign b = a;
    endmodule
    """
    entities, _ = _run(src)
    kinds = []
    for a in _by_type(entities, "Assignment"):
        ak = a.attributes.get("assign_kind")
        if ak:
            kinds.append(ak)
    assert "nonblocking" in kinds
    assert "blocking" in kinds
    assert "continuous" in kinds


# ---------------------------------------------------------------------------
# Stable IDs
# ---------------------------------------------------------------------------


def test_stable_ids_across_runs() -> None:
    src = """
    module m_stable;
      logic a, b, c;
      always_comb begin
        if (a) c = b;
        else c = 1'b0;
      end
    endmodule
    """
    e1, _ = _run(src)
    e2, _ = _run(src)
    names1 = sorted(e.name for e in e1)
    names2 = sorted(e.name for e in e2)
    assert names1 == names2
