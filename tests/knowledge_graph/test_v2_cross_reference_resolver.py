"""Tests for the v2 cross-reference resolver (Wave 1 / track C).

The resolver consumes a pyslang elaborated ``NamedValueExpression`` (or
hierarchical reference / selector) and returns the *canonical entity name*
that a v1-compatible Signal/Port/Parameter node would carry, plus the edge
attributes used for the ``references`` triple.

Naming choice (documented):
    Hierarchical references resolve to the fully-qualified hierarchical
    path of the underlying Symbol — i.e. one ``references`` edge with
    object ``top.u_inst.u_sub.internal``. Multi-hop walk through Instance
    nodes is left as a query-side helper (see schema doc, open-question 2).
"""
from __future__ import annotations

import pytest

pytest.importorskip("pyslang", reason="pyslang is a hard dep — install required")

import pyslang as _ps  # noqa: E402

from kgweave.knowledge_graph.extraction.sv_xref_resolver import (  # noqa: E402
    resolve_named_value,
    emit_reference_triple,
    XREF_SOURCE,
)
from kgweave.knowledge_graph.common import Triple  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _compile(src: str) -> "_ps.Compilation":
    comp = _ps.Compilation()
    comp.addSyntaxTree(_ps.SyntaxTree.fromText(src))
    return comp


def _top(comp: "_ps.Compilation", name: str) -> "_ps.InstanceSymbol":
    for inst in comp.getRoot().topInstances:
        if inst.name == name:
            return inst
    raise AssertionError(f"top {name!r} not found")


def _collect_named_values(node) -> list:
    """Visit every NamedValue / HierarchicalValue expression under ``node``."""
    out: list = []

    def visit(n):
        k = getattr(n, "kind", None)
        if k is None:
            return
        ks = str(k)
        if ks.endswith("NamedValue") or ks.endswith("HierarchicalValue"):
            out.append(n)

    node.visit(visit)
    return out


def _continuous_assigns(inst: "_ps.InstanceSymbol") -> list:
    return [m for m in inst.body if m.kind == _ps.SymbolKind.ContinuousAssign]


def _proc_blocks(inst: "_ps.InstanceSymbol") -> list:
    return [m for m in inst.body if m.kind == _ps.SymbolKind.ProceduralBlock]


# ---------------------------------------------------------------------------
# 1. Local signal reference
# ---------------------------------------------------------------------------


def test_local_signal_resolves_to_module_qualified_name() -> None:
    src = """
    module m(input logic a, output logic y);
      logic n;
      assign n = a;
      assign y = n;
    endmodule
    """
    comp = _compile(src)
    inst = _top(comp, "m")
    refs: list[str] = []
    for ca in _continuous_assigns(inst):
        for nv in _collect_named_values(ca.assignment):
            res = resolve_named_value(nv)
            assert res is not None
            refs.append(res[0])
    # Expect references to m.a, m.n (twice — once as RHS, once as LHS),
    # m.y as LHS. All under module 'm'.
    assert "m.a" in refs
    assert "m.n" in refs
    assert "m.y" in refs
    # No leakage of bare names (must be qualified):
    assert all("." in r for r in refs), refs


# ---------------------------------------------------------------------------
# 2. Local port reference resolves to existing Port entity name shape
# ---------------------------------------------------------------------------


def test_local_port_reference_resolves_to_port_qualified_name() -> None:
    src = """
    module m(input logic a, output logic y);
      assign y = a;
    endmodule
    """
    comp = _compile(src)
    inst = _top(comp, "m")
    ca = _continuous_assigns(inst)[0]
    nvs = _collect_named_values(ca.assignment)
    names = {resolve_named_value(nv)[0] for nv in nvs}
    # v1 mints ports as <module>.<port_name>.
    assert "m.a" in names
    assert "m.y" in names


# ---------------------------------------------------------------------------
# 3. Hierarchical reference
# ---------------------------------------------------------------------------


def test_hierarchical_reference_resolves_to_fully_qualified_path() -> None:
    src = """
    module sub(input logic s_in, output logic s_out);
      logic internal;
      assign internal = s_in;
      assign s_out = internal;
    endmodule

    module mid(input logic m_in, output logic m_out);
      sub u_sub(.s_in(m_in), .s_out(m_out));
    endmodule

    module top(input logic d, output logic q);
      logic tap;
      mid u_inst(.m_in(d), .m_out(q));
      assign tap = u_inst.u_sub.internal;
    endmodule
    """
    comp = _compile(src)
    top = _top(comp, "top")
    # Find the assign that has a hierarchical reference.
    hier_targets: list[tuple[str, dict]] = []
    for ca in _continuous_assigns(top):
        for nv in _collect_named_values(ca.assignment):
            res = resolve_named_value(nv)
            assert res is not None
            hier_targets.append(res)
    names = [n for n, _ in hier_targets]
    # The hierarchical reference resolves to the full path.
    assert "top.u_inst.u_sub.internal" in names
    # And carries hop info in attrs (number of dots > 1 implies hierarchical).
    rec = next((a for n, a in hier_targets if n == "top.u_inst.u_sub.internal"))
    assert rec.get("hierarchical") is True
    assert rec.get("hop_path") == ["top", "u_inst", "u_sub", "internal"]


# ---------------------------------------------------------------------------
# 4. Unresolved sentinel
# ---------------------------------------------------------------------------


def test_unresolved_emits_low_tier_sentinel() -> None:
    """A NamedValue-shaped object with no resolvable symbol must yield None
    from resolve_named_value, and emit_reference_triple must produce a
    low-tier sentinel triple."""

    class _StubExpr:
        # mimic a pyslang expression that has a NamedValue-ish kind but
        # no resolvable symbol.
        class _Kind:
            def __str__(self) -> str:
                return "ExpressionKind.NamedValue"

        kind = _Kind()
        symbol = None

    res = resolve_named_value(_StubExpr())
    assert res is None

    triple = emit_reference_triple(
        subject="m.always_ff_0.expr_42",
        expr=_StubExpr(),
        textual_ref="some_undef_sig",
        source="src.sv",
    )
    assert isinstance(triple, Triple)
    assert triple.predicate == "references"
    assert triple.object == "some_undef_sig"
    assert triple.confidence_tier == "low"
    assert triple.resolved is False
    assert triple.layer == "ast"


# ---------------------------------------------------------------------------
# 5. Generate-loop iteration references
# ---------------------------------------------------------------------------


def test_generate_loop_per_iteration_resolution() -> None:
    src = """
    module m(input logic [3:0] d, output logic [3:0] q);
      genvar i;
      generate
        for (i = 0; i < 4; i++) begin : g
          logic local_sig;
          assign local_sig = d[i];
          assign q[i] = local_sig;
        end
      endgenerate
    endmodule
    """
    comp = _compile(src)
    top = _top(comp, "m")
    # Walk into the generate block array.
    per_iter_names: set[str] = set()
    for member in top.body:
        if member.kind != _ps.SymbolKind.GenerateBlockArray:
            continue
        for block in member:
            for ca in (m for m in block if m.kind == _ps.SymbolKind.ContinuousAssign):
                for nv in _collect_named_values(ca.assignment):
                    res = resolve_named_value(nv)
                    if res is not None:
                        per_iter_names.add(res[0])
    # Each iteration's local_sig must be a DISTINCT canonical name.
    iter_locals = {n for n in per_iter_names if "local_sig" in n}
    assert iter_locals == {
        "m.g[0].local_sig",
        "m.g[1].local_sig",
        "m.g[2].local_sig",
        "m.g[3].local_sig",
    }, iter_locals


# ---------------------------------------------------------------------------
# 6. layer="ast" on every emitted triple
# ---------------------------------------------------------------------------


def test_emit_reference_triple_carries_layer_ast() -> None:
    src = """
    module m(input logic a, output logic y);
      assign y = a;
    endmodule
    """
    comp = _compile(src)
    inst = _top(comp, "m")
    ca = _continuous_assigns(inst)[0]
    nvs = _collect_named_values(ca.assignment)

    triples = []
    for i, nv in enumerate(nvs):
        res = resolve_named_value(nv)
        assert res is not None
        canonical, attrs = res
        t = emit_reference_triple(
            subject=f"m.assign_0.expr_{i}",
            expr=nv,
            textual_ref=canonical,
            source="src.sv",
            resolved_target=canonical,
            attrs=attrs,
        )
        triples.append(t)
    assert triples, "expected at least one emitted triple"
    for t in triples:
        assert t.layer == "ast", f"{t} missing layer='ast'"
        assert t.predicate == "references"
        assert t.confidence_tier == "high"
        assert t.resolved is True
        assert t.extractor_source == XREF_SOURCE


# ---------------------------------------------------------------------------
# 7. Idempotence — same logical signal => same canonical name
# ---------------------------------------------------------------------------


def test_resolution_is_stable_across_multiple_references() -> None:
    src = """
    module m(input logic a, input logic b, output logic y, output logic z);
      assign y = a & b;
      assign z = a | b;
    endmodule
    """
    comp = _compile(src)
    inst = _top(comp, "m")
    seen_for_a: set[str] = set()
    seen_for_b: set[str] = set()
    for ca in _continuous_assigns(inst):
        for nv in _collect_named_values(ca.assignment):
            res = resolve_named_value(nv)
            assert res is not None
            sym = getattr(nv, "symbol", None)
            if getattr(sym, "name", None) == "a":
                seen_for_a.add(res[0])
            elif getattr(sym, "name", None) == "b":
                seen_for_b.add(res[0])
    # Each logical signal canonicalises to exactly one string across all
    # references in the module.
    assert seen_for_a == {"m.a"}
    assert seen_for_b == {"m.b"}
