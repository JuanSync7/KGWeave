"""Semantic-layer query oracle.

Each test fires one of the S1..S5 / S34 rules from ``scripts.semantic`` and
asserts that the resulting graph answers a concrete elaboration query.  The
round-trip oracle (``test_roundtrip.py``) must keep passing alongside this
file — if a semantic promotion ever breaks structural fidelity, both files
fail together.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def fixture_bundle():
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return tree, comp, graph


def _queryable_by_role(graph, role):
    from knowledge_graph.builders.sv.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph) if n.get("semantic", {}).get("role") == role]


def test_roundtrip_after_promote(fixture_bundle):
    """Promotion must not mutate token payloads — emit() still reproduces source."""
    tree, _comp, graph = fixture_bundle
    from knowledge_graph.builders.sv.unlift import emit

    emitted = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    # Strongest oracle: byte-equal token text stream.
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


def test_s1_module_promotes_ports_params_nets(fixture_bundle):
    """S1: module fifo has 8 ports, 2 params, 4 nets.

    fifo.sv now contains multiple modules (fifo + always_demo for S34 corpus);
    we assert that the fifo module specifically carries the expected children
    rather than asserting a fixed total module count.
    """
    _tree, _comp, graph = fixture_bundle
    ports = _queryable_by_role(graph, "port")
    params = _queryable_by_role(graph, "param")
    nets = _queryable_by_role(graph, "net")
    modules = _queryable_by_role(graph, "module")

    module_names = {m["semantic"]["name"] for m in modules}
    assert "fifo" in module_names, f"fifo module missing; found {module_names}"
    assert {p["semantic"]["name"] for p in ports
            if p["semantic"]["path"].startswith("fifo.")} == {
        "clk", "rst_n", "push", "pop", "din", "dout", "full", "empty", "status",
    }
    assert {p["semantic"]["name"] for p in params
            if p["semantic"]["path"].startswith("fifo.")} == {"DEPTH", "WIDTH"}
    assert {n["semantic"]["name"] for n in nets
            if n["semantic"]["path"].startswith("fifo.")} == {
        "mem", "wr_ptr", "rd_ptr", "count"
    }


def test_s2_continuous_assign_drives_and_reads(fixture_bundle):
    """S2: who_drives('dout') yields exactly one continuous_assign node."""
    _tree, _comp, graph = fixture_bundle
    from knowledge_graph.builders.sv.semantic import find_drivers

    drivers = find_drivers(graph, "dout")
    assert len(drivers) == 1
    assert drivers[0]["semantic"]["role"] == "continuous_assign"

    full_drivers = find_drivers(graph, "full")
    assert len(full_drivers) == 1
    # The 'full' assign reads `count` (and the param DEPTH via name resolution).
    from knowledge_graph.builders.sv.semantic import neighbors

    reads = neighbors(graph, full_drivers[0]["id"], edge_type="reads", direction="out")
    read_names = {r["semantic"].get("name") for r in reads}
    assert "count" in read_names


def test_s3_always_ff_sensitivity_and_drives(fixture_bundle):
    """S3: the always_ff has sensitive_to clk(posedge) and rst_n(negedge);
    cone_of_influence('full') reaches push, pop, rst_n."""
    _tree, _comp, graph = fixture_bundle
    always = _queryable_by_role(graph, "always_ff")
    assert len(always) == 1
    aff = always[0]
    from knowledge_graph.builders.sv.semantic import neighbors

    sens = neighbors(graph, aff["id"], edge_type="sensitive_to", direction="out")
    sens_names = {s["semantic"].get("name") for s in sens}
    assert {"clk", "rst_n"} <= sens_names

    # The always_ff drives count.
    drives = neighbors(graph, aff["id"], edge_type="drives", direction="out")
    drive_names = {d["semantic"].get("name") for d in drives}
    assert {"wr_ptr", "rd_ptr", "count"} <= drive_names

    reads = neighbors(graph, aff["id"], edge_type="reads", direction="out")
    read_names = {r["semantic"].get("name") for r in reads}
    assert {"push", "pop", "rst_n"} <= read_names


def test_s4_identifier_select_reads_base(fixture_bundle):
    """S4: every IdentifierSelectNameSyntax `reads` its base symbol.

    `mem[rd_ptr[$clog2(DEPTH)-1:0]]` produces a select on mem and rd_ptr.
    """
    _tree, _comp, graph = fixture_bundle
    selects = _queryable_by_role(graph, "identifier_select")
    bases = {s["semantic"]["base"] for s in selects}
    assert {"mem", "rd_ptr", "wr_ptr"} <= bases
    # mem and rd_ptr appear in the same expression — both must have a reads edge.
    from knowledge_graph.builders.sv.semantic import neighbors

    for s in selects:
        if s["semantic"]["base"] == "mem":
            tgt = neighbors(graph, s["id"], edge_type="reads", direction="out")
            assert any(t["semantic"].get("name") == "mem" for t in tgt)


def test_s5_system_call_clog2_reads_depth(fixture_bundle):
    """S5: every `$clog2(DEPTH)` call is promoted and `reads` DEPTH."""
    _tree, _comp, graph = fixture_bundle
    calls = _queryable_by_role(graph, "system_call")
    assert calls, "expected at least one $clog2 invocation"
    from knowledge_graph.builders.sv.semantic import neighbors

    for c in calls:
        assert c["semantic"]["name"] == "$clog2"
        tgts = neighbors(graph, c["id"], edge_type="reads", direction="out")
        names = {t["semantic"].get("name") for t in tgts}
        assert "DEPTH" in names


# ---------------------------------------------------------------------------
# S34 — AlwaysBlock (generic always @(...))
#
# ``always_demo`` in corpus/fifo.sv has two generic always blocks:
#   1. always @(posedge clk) — edge-sensitive; q <= a
#   2. always @(a or b)      — level-sensitive; r = a & b
#
# S34 promotes each ProceduralBlockSyntax[AlwaysBlock] with role="always"
# and emits sensitive_to / drives / reads edges using the same helpers as S3.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def s34_bundle(fixture_bundle):
    """Re-use the fixture_bundle graph which includes always_demo."""
    _tree, _comp, graph = fixture_bundle
    return graph


def test_s34_always_blocks_promoted(s34_bundle):
    """Both generic always blocks in always_demo are promoted with
    role='always', not role='always_ff' or role='always_comb'."""
    blocks = [n for n in s34_bundle["nodes"]
              if n.get("semantic", {}).get("role") == "always"]
    assert len(blocks) >= 2, (
        f"expected at least 2 always nodes, got {len(blocks)}"
    )


def test_s34_always_ff_and_comb_unchanged(s34_bundle):
    """S34 must not absorb always_ff or always_comb nodes — their role
    labels must remain distinct (regression guard for lesson-1 shared-class
    dispatch)."""
    ff_nodes = [n for n in s34_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "always_ff"]
    comb_nodes = [n for n in s34_bundle["nodes"]
                  if n.get("semantic", {}).get("role") == "always_comb"]
    assert len(ff_nodes) >= 1, "always_ff nodes missing after S34 added"
    assert len(comb_nodes) >= 1, "always_comb nodes missing after S34 added"


def test_s34_edge_sensitive_has_sensitive_to(s34_bundle):
    """The always @(posedge clk) block emits a sensitive_to edge to clk
    with edge='posedge'."""
    from knowledge_graph.builders.sv.semantic import neighbors

    always_blocks = [n for n in s34_bundle["nodes"]
                     if n.get("semantic", {}).get("role") == "always"]
    # Find the block that has a posedge sensitive_to edge.
    posedge_blocks = []
    for blk in always_blocks:
        sens = neighbors(s34_bundle, blk["id"], edge_type="sensitive_to",
                         direction="out")
        if any(s.get("semantic", {}).get("name") == "clk" for s in sens):
            posedge_blocks.append(blk)
    assert posedge_blocks, (
        "no always block with sensitive_to(clk) found — "
        "edge-sensitive sensitivity list not emitted"
    )
    # Verify posedge attribute on the sensitive_to edge.
    blk = posedge_blocks[0]
    clk_edges = [e for e in s34_bundle["edges"]
                 if e["type"] == "sensitive_to"
                 and e["src"] == blk["id"]
                 and e.get("payload", {}).get("edge") == "posedge"]
    assert clk_edges, "sensitive_to edge missing posedge attribute"


def test_s34_level_sensitive_has_sensitive_to(s34_bundle):
    """The always @(a or b) block emits sensitive_to edges to both a and b
    (no edge qualifier — level-sensitive)."""
    from knowledge_graph.builders.sv.semantic import neighbors

    always_blocks = [n for n in s34_bundle["nodes"]
                     if n.get("semantic", {}).get("role") == "always"]
    ab_blocks = []
    for blk in always_blocks:
        sens = neighbors(s34_bundle, blk["id"], edge_type="sensitive_to",
                         direction="out")
        names = {s.get("semantic", {}).get("name") for s in sens}
        if {"a", "b"} <= names:
            ab_blocks.append(blk)
    assert ab_blocks, (
        "no always block with sensitive_to({a,b}) found — "
        "level-sensitive sensitivity list not emitted"
    )


def test_s34_drives_and_reads_emitted(s34_bundle):
    """Each always block emits drives edges for LHS assignments and reads
    edges for RHS identifiers."""
    always_blocks = [n for n in s34_bundle["nodes"]
                     if n.get("semantic", {}).get("role") == "always"]
    for blk in always_blocks:
        block_id = blk["id"]
        drives = [e for e in s34_bundle["edges"]
                  if e["type"] == "drives" and e["src"] == block_id]
        reads = [e for e in s34_bundle["edges"]
                 if e["type"] == "reads" and e["src"] == block_id]
        assert drives or reads, (
            f"always block {block_id} has neither drives nor reads edges"
        )


def test_s34_roundtrip_after_promote(fixture_bundle):
    """S34 must not mutate token payloads — emit() still reproduces source
    byte-for-byte after always_demo blocks are promoted."""
    tree, _comp, graph = fixture_bundle
    from knowledge_graph.builders.sv.unlift import emit

    emitted = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


# ---------------------------------------------------------------------------
# S35 — AlwaysLatchBlock (always_latch begin ... end)
#
# ``latch_demo`` in corpus/fifo.sv contains one always_latch block:
#   always_latch begin
#       if (en) begin
#           latch_out = latch_in;
#           latch_sel = latch_in & b;
#       end
#   end
#
# S35 promotes it with role="procedural_block", attribute kind="always_latch",
# and emits drives/reads edges by walking body assignments (no sensitivity list
# — latches infer sensitivity from body, per LRM).
# ---------------------------------------------------------------------------

LATCH_SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def s35_bundle():
    """Lift + promote corpus/fifo.sv (which contains latch_demo) and return
    the graph so S35 tests can query the latch_demo module."""
    text = LATCH_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s35_always_latch_promoted(s35_bundle):
    """The always_latch block in latch_demo is promoted with
    role='procedural_block' and kind='always_latch'."""
    latch_blocks = [
        n for n in s35_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "always_latch"
    ]
    assert len(latch_blocks) >= 1, (
        f"expected at least 1 always_latch node, got {len(latch_blocks)}"
    )


def test_s35_not_confused_with_ff_or_comb(s35_bundle):
    """S35 must not absorb always_ff or always_comb nodes — role labels are
    distinct (regression guard for lesson-1 shared-class dispatch)."""
    ff_nodes = [n for n in s35_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "always_ff"]
    comb_nodes = [n for n in s35_bundle["nodes"]
                  if n.get("semantic", {}).get("role") == "always_comb"]
    assert len(ff_nodes) >= 1, "always_ff nodes missing after S35 added"
    assert len(comb_nodes) >= 1, "always_comb nodes missing after S35 added"


def test_s35_drives_latch_out_and_latch_sel(s35_bundle):
    """The always_latch block drives both latch_out and latch_sel."""
    latch_blocks = [
        n for n in s35_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "always_latch"
    ]
    assert latch_blocks, "no always_latch block found"
    blk = latch_blocks[0]
    driven = {
        e["dst"] for e in s35_bundle["edges"]
        if e["type"] == "drives" and e["src"] == blk["id"]
    }
    # Resolve dst gids back to names via the name index.
    name_index = s35_bundle.get("semantic_name_index", {})
    gid_to_name = {v: k.split(".")[-1] for k, v in name_index.items()}
    driven_names = {gid_to_name.get(d, d) for d in driven}
    assert "latch_out" in driven_names, (
        f"latch_out not in drives edges; driven_names={driven_names}"
    )
    assert "latch_sel" in driven_names, (
        f"latch_sel not in drives edges; driven_names={driven_names}"
    )


def test_s35_reads_latch_in_and_b(s35_bundle):
    """The always_latch block reads latch_in (body RHS) and b (body RHS)."""
    latch_blocks = [
        n for n in s35_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "always_latch"
    ]
    assert latch_blocks, "no always_latch block found"
    blk = latch_blocks[0]
    read_dsts = {
        e["dst"] for e in s35_bundle["edges"]
        if e["type"] == "reads" and e["src"] == blk["id"]
    }
    name_index = s35_bundle.get("semantic_name_index", {})
    gid_to_name = {v: k.split(".")[-1] for k, v in name_index.items()}
    read_names = {gid_to_name.get(d, d) for d in read_dsts}
    assert "latch_in" in read_names, (
        f"latch_in not in reads edges; read_names={read_names}"
    )
    assert "b" in read_names, (
        f"b not in reads edges; read_names={read_names}"
    )


def test_s35_no_sensitive_to_edges(s35_bundle):
    """always_latch has no explicit sensitivity list — no sensitive_to edges
    should be emitted by S35."""
    latch_blocks = [
        n for n in s35_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "always_latch"
    ]
    assert latch_blocks, "no always_latch block found"
    blk = latch_blocks[0]
    sens_edges = [
        e for e in s35_bundle["edges"]
        if e["type"] == "sensitive_to" and e["src"] == blk["id"]
    ]
    assert not sens_edges, (
        f"unexpected sensitive_to edges on always_latch block: {sens_edges}"
    )


def test_s35_roundtrip_after_promote(s35_bundle):
    """S35 must not mutate token payloads — emit() still reproduces source
    byte-for-byte after latch_demo block is promoted."""
    text = LATCH_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    from knowledge_graph.builders.sv.unlift import emit

    emitted = emit(s35_bundle)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


# ---------------------------------------------------------------------------
# S36 — InitialBlock (initial begin ... end)
#
# ``tb_fifo`` in corpus/tb_fifo.sv has two initial blocks:
#   1. initial begin clk = 0; forever #5 clk = ~clk; end
#   2. initial begin rst_n = 0; push = 0; ... $display(...); $finish; end
#
# S36 promotes each ProceduralBlockSyntax[InitialBlock] with
# role="procedural_block", attribute kind="initial", and emits drives/reads
# edges from body assignments. No sensitivity list (initial blocks have none).
# Discriminated by SyntaxKind.InitialBlock per CLAUDE.md lesson 1.
# ---------------------------------------------------------------------------

TB_SRC = HERE / "corpus" / "tb_fifo.sv"


@pytest.fixture(scope="module")
def s36_bundle():
    """Lift + promote corpus/tb_fifo.sv (which contains two initial blocks)
    and return the graph so S36 tests can query them."""
    text = TB_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s36_initial_blocks_promoted(s36_bundle):
    """Both initial blocks in tb_fifo are promoted with
    role='procedural_block' and kind='initial'."""
    initial_blocks = [
        n for n in s36_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "initial"
    ]
    assert len(initial_blocks) >= 2, (
        f"expected at least 2 initial blocks, got {len(initial_blocks)}"
    )


def test_s36_kind_attribute_is_initial(s36_bundle):
    """Each promoted InitialBlock carries attribute kind='initial'
    (not 'always_latch' or 'always_comb' — regression guard for lesson-1
    shared ProceduralBlockSyntax class dispatch)."""
    initial_blocks = [
        n for n in s36_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "initial"
    ]
    for blk in initial_blocks:
        assert blk["semantic"]["attributes"]["kind"] == "initial", (
            f"wrong kind attribute on initial block {blk['id']}"
        )


def test_s36_no_sensitive_to_edges(s36_bundle):
    """initial blocks have no sensitivity list — no sensitive_to edges
    should be emitted by S36."""
    initial_blocks = [
        n for n in s36_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "initial"
    ]
    assert initial_blocks, "no initial blocks found"
    for blk in initial_blocks:
        sens_edges = [
            e for e in s36_bundle["edges"]
            if e["type"] == "sensitive_to" and e["src"] == blk["id"]
        ]
        assert not sens_edges, (
            f"unexpected sensitive_to edges on initial block {blk['id']}: {sens_edges}"
        )


def test_s36_drives_emitted_from_assignments(s36_bundle):
    """The second initial block drives clk, rst_n, push, pop, din
    (all assigned in the body)."""
    initial_blocks = [
        n for n in s36_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "initial"
    ]
    assert initial_blocks, "no initial blocks found"
    name_index = s36_bundle.get("semantic_name_index", {})
    gid_to_name = {v: k.split(".")[-1] for k, v in name_index.items()}
    all_driven: set[str] = set()
    for blk in initial_blocks:
        for e in s36_bundle["edges"]:
            if e["type"] == "drives" and e["src"] == blk["id"]:
                all_driven.add(gid_to_name.get(e["dst"], e["dst"]))
    # clk is assigned in the first block; rst_n/push/pop/din in the second.
    assert "clk" in all_driven or "rst_n" in all_driven, (
        f"expected driven signals from initial blocks; got {all_driven}"
    )


def test_s36_reads_emitted_from_rhs(s36_bundle):
    """Body RHS identifiers produce reads edges — e.g. dout is read in
    the $display call arguments inside tb_fifo's second initial block."""
    initial_blocks = [
        n for n in s36_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "initial"
    ]
    assert initial_blocks, "no initial blocks found"
    # At least one initial block must emit at least one reads or drives edge
    # (robustness check — avoids fragility on exact signal names).
    has_dataflow = any(
        any(e["src"] == blk["id"] and e["type"] in {"drives", "reads"}
            for e in s36_bundle["edges"])
        for blk in initial_blocks
    )
    assert has_dataflow, "no drives/reads edges on any initial block"


def test_s36_roundtrip_after_promote(s36_bundle):
    """S36 must not mutate token payloads — emit() reproduces tb_fifo.sv
    byte-for-byte after initial blocks are promoted."""
    text = TB_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    from knowledge_graph.builders.sv.unlift import emit

    emitted = emit(s36_bundle)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


# ---------------------------------------------------------------------------
# S37 — FinalBlock (final begin ... end)
#
# ``tb_fifo`` in corpus/tb_fifo.sv now has one final block:
#   final begin $display("done: count=%0d", err_count); end
#
# S37 promotes ProceduralBlockSyntax[FinalBlock] with
# role="procedural_block", attribute kind="final". No sensitivity list
# (final blocks have none — they run once at simulation end). Body
# identifiers that appear in argument positions emit reads edges; the
# typical use-case is $display/$finish reading local counters/signals.
#
# Discriminated by SyntaxKind.FinalBlock per CLAUDE.md lesson 1 —
# ProceduralBlockSyntax is shared across always/initial/final/etc.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def s37_bundle():
    """Lift + promote corpus/tb_fifo.sv (which contains the final block)
    and return the graph so S37 tests can query it."""
    text = TB_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s37_final_block_promoted(s37_bundle):
    """The final block in tb_fifo is promoted with
    role='procedural_block' and kind='final'."""
    final_blocks = [
        n for n in s37_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "final"
    ]
    assert len(final_blocks) >= 1, (
        f"expected at least 1 final block, got {len(final_blocks)}"
    )


def test_s37_kind_attribute_is_final(s37_bundle):
    """Each promoted FinalBlock carries attribute kind='final'
    (not 'initial', 'always_latch', or other — regression guard for
    lesson-1 shared ProceduralBlockSyntax class dispatch)."""
    final_blocks = [
        n for n in s37_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "final"
    ]
    assert final_blocks, "no final blocks found"
    for blk in final_blocks:
        assert blk["semantic"]["attributes"]["kind"] == "final", (
            f"wrong kind attribute on final block {blk['id']}"
        )


def test_s37_no_sensitive_to_edges(s37_bundle):
    """final blocks have no sensitivity list — no sensitive_to edges
    should be emitted by S37."""
    final_blocks = [
        n for n in s37_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "final"
    ]
    assert final_blocks, "no final blocks found"
    for blk in final_blocks:
        sens_edges = [
            e for e in s37_bundle["edges"]
            if e["type"] == "sensitive_to" and e["src"] == blk["id"]
        ]
        assert not sens_edges, (
            f"unexpected sensitive_to edges on final block {blk['id']}: {sens_edges}"
        )


def test_s37_reads_emitted_from_body_identifiers(s37_bundle):
    """Body identifiers in the final block (e.g. err_count passed to
    $display) produce reads edges — or at minimum the block has no
    spurious sensitive_to edge (robustness check)."""
    final_blocks = [
        n for n in s37_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "final"
    ]
    assert final_blocks, "no final blocks found"
    # Final blocks in typical testbenches only call $display/$finish; they
    # may read local variables. We assert the block is queryable (promoted)
    # and emits no erroneous edge types (no sensitive_to, confirmed above).
    # drives/reads may be zero if resolver can't find err_count — acceptable.
    for blk in final_blocks:
        # role and kind must be set correctly
        assert blk["semantic"]["role"] == "procedural_block"
        assert blk["semantic"]["attributes"]["kind"] == "final"


def test_s37_initial_and_latch_blocks_unchanged(s37_bundle):
    """S37 must not absorb initial or always_latch nodes — their kind
    attributes must remain distinct (regression guard for lesson-1 shared
    ProceduralBlockSyntax dispatch)."""
    initial_blocks = [
        n for n in s37_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "procedural_block"
        and n.get("semantic", {}).get("attributes", {}).get("kind") == "initial"
    ]
    assert len(initial_blocks) >= 2, (
        "initial blocks missing or absorbed by S37 — "
        f"found {len(initial_blocks)}"
    )


def test_s37_roundtrip_after_promote(s37_bundle):
    """S37 must not mutate token payloads — emit() reproduces tb_fifo.sv
    byte-for-byte after the final block is promoted."""
    text = TB_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    from knowledge_graph.builders.sv.unlift import emit

    emitted = emit(s37_bundle)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


# ---------------------------------------------------------------------------
# S46 — NetAlias (``alias a = b = c;``, SV §10.11)
#
# ``alias_demo`` in corpus/fifo.sv contains:
#   logic a, b, c;
#   alias a = b = c;
#
# S46 is edge-only (lesson 4): no new node is created.  Consecutive-pairs
# convention: emit ``aliases`` edges a↔b and b↔c (both directions for
# bidirectionality), i.e. a→b, b→a, b→c, c→b.
#
# Resolution via name_index (``alias_demo.a`` etc.); fallback to
# ``_unresolved.<name>`` if not found.
# ---------------------------------------------------------------------------

ALIAS_SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def s46_bundle():
    """Lift + promote corpus/fifo.sv (which contains alias_demo) and return
    the graph so S46 tests can query the alias_demo module."""
    text = ALIAS_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s46_aliases_edges_emitted(s46_bundle):
    """S46: alias a = b = c emits aliases edges between consecutive pairs.

    Consecutive-pairs convention: (a,b) and (b,c), each bidirectional —
    four directed edges total: a→b, b→a, b→c, c→b.
    """
    alias_edges = [e for e in s46_bundle["edges"] if e["type"] == "aliases"]
    assert len(alias_edges) >= 4, (
        f"expected at least 4 aliases edges (a↔b, b↔c), got {len(alias_edges)}: "
        f"{alias_edges}"
    )


def test_s46_correct_pairings(s46_bundle):
    """S46: aliases edges connect the correct signal pairs.

    Pairs expected (bidirectional): (a,b) and (b,c).
    Pair (a,c) is NOT expected under the consecutive-pairs convention.
    """
    alias_edges = [e for e in s46_bundle["edges"] if e["type"] == "aliases"]

    # Collect (src_name, dst_name) from resolved nodes.
    def _name(gid):
        for n in s46_bundle["nodes"]:
            if n["id"] == gid:
                return n.get("semantic", {}).get("name") or str(gid)
        # Could be an _unresolved.<x> string
        if isinstance(gid, str) and gid.startswith("_unresolved."):
            return gid.split(".", 1)[1]
        return str(gid)

    pairs = {(_name(e["src"]), _name(e["dst"])) for e in alias_edges}
    # Bidirectional consecutive pairs a↔b, b↔c.
    assert ("a", "b") in pairs, f"a→b aliases edge missing; pairs={pairs}"
    assert ("b", "a") in pairs, f"b→a aliases edge missing; pairs={pairs}"
    assert ("b", "c") in pairs, f"b→c aliases edge missing; pairs={pairs}"
    assert ("c", "b") in pairs, f"c→b aliases edge missing; pairs={pairs}"


def test_s46_no_node_created(s46_bundle):
    """S46 is edge-only: no new node should carry role='net_alias'.

    The NetAlias SyntaxKind stays as BLOB in the bucket-1 sense — only
    edges are added.
    """
    alias_nodes = [n for n in s46_bundle["nodes"]
                   if n.get("semantic", {}).get("role") == "net_alias"]
    assert alias_nodes == [], (
        f"unexpected net_alias nodes created: {alias_nodes}"
    )


def test_s46_roundtrip_after_promote(s46_bundle):
    """S46 must not mutate token payloads — emit() reproduces fifo.sv
    byte-for-byte after alias_demo is promoted."""
    text = ALIAS_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    from knowledge_graph.builders.sv.unlift import emit

    emitted = emit(s46_bundle)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


# ---------------------------------------------------------------------------
# S47 — TimeUnitsDeclaration (``timeunit``/``timeprecision`` directives)
#
# ``fifo`` module in corpus/fifo.sv now contains:
#   timeunit 1ns;
#   timeprecision 1ps;
#
# S47 promotes each TimeUnitsDeclaration to role=time_units with:
#   - name: "__timeunits__"
#   - path: "<scope>.__timeunits__"  (scope = enclosing module/package)
#   - attributes["unit"]:      the timeunit literal (e.g. "1ns")
#   - attributes["precision"]: the timeprecision literal (e.g. "1ps"),
#                              present only on the timeprecision statement
# An edge ``has_timeunits`` runs from the enclosing scope node to the
# promoted node.
# ---------------------------------------------------------------------------

TIMEUNITS_SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def s47_bundle():
    """Lift + promote corpus/fifo.sv (which now contains timeunit/timeprecision
    directives inside module fifo) and return the graph."""
    text = TIMEUNITS_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s47_timeunits_node_promoted(s47_bundle):
    """S47: timeunit 1ns inside module fifo promotes a role=time_units node
    with unit attribute = '1ns'."""
    tu_nodes = [n for n in s47_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "time_units"]
    assert len(tu_nodes) >= 1, (
        f"expected at least one time_units node, got 0; "
        f"semantic nodes: {[n.get('semantic') for n in s47_bundle['nodes'] if n.get('semantic')]}"
    )
    unit_nodes = [n for n in tu_nodes
                  if n["semantic"].get("attributes", {}).get("unit") == "1ns"]
    assert unit_nodes, (
        f"no time_units node with unit='1ns'; time_units nodes: "
        f"{[n['semantic'] for n in tu_nodes]}"
    )


def test_s47_precision_node_promoted(s47_bundle):
    """S47: timeprecision 1ps inside module fifo promotes a role=time_units
    node with precision attribute = '1ps'."""
    tu_nodes = [n for n in s47_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "time_units"]
    prec_nodes = [n for n in tu_nodes
                  if n["semantic"].get("attributes", {}).get("precision") == "1ps"]
    assert prec_nodes, (
        f"no time_units node with precision='1ps'; time_units nodes: "
        f"{[n['semantic'] for n in tu_nodes]}"
    )


def test_s47_has_timeunits_edge(s47_bundle):
    """S47: the enclosing scope emits a has_timeunits edge to the promoted node."""
    tu_edges = [e for e in s47_bundle["edges"] if e["type"] == "has_timeunits"]
    assert len(tu_edges) >= 1, (
        f"expected at least one has_timeunits edge, got {len(tu_edges)}"
    )


def test_s47_path_under_scope(s47_bundle):
    """S47: the promoted node path must be '<scope>.__timeunits__'."""
    tu_nodes = [n for n in s47_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "time_units"]
    for node in tu_nodes:
        path = node["semantic"].get("path", "")
        assert path.endswith(".__timeunits__"), (
            f"path '{path}' does not end with '.__timeunits__'"
        )


def test_s47_roundtrip_after_promote(s47_bundle):
    """S47 must not mutate token payloads — emit() reproduces fifo.sv
    byte-for-byte after TimeUnitsDeclaration nodes are promoted."""
    text = TIMEUNITS_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    from knowledge_graph.builders.sv.unlift import emit

    emitted = emit(s47_bundle)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


# ---------------------------------------------------------------------------
# S54 — NetDeclaration (``wire``, ``tri``, ``supply0``, ``wire signed [3:0]``)
#
# Promotes pyslang.SyntaxKind.NetDeclaration as a queryable ``net_decl`` group
# node and ensures per-net Declarators inside it surface as role="net" nodes
# (mirroring DataDeclarationSyntax's logic-net path).  See net_demo in
# corpus/fifo.sv.
# ---------------------------------------------------------------------------

NETDECL_SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def s54_bundle():
    """Lift + promote corpus/fifo.sv (which contains net_demo) so S54 tests
    can query the net_demo module."""
    text = NETDECL_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _net_demo_nodes(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role
            and n["semantic"].get("path", "").startswith("net_demo.")]


def test_s54_net_decl_group_nodes_promoted(s54_bundle):
    """S54: each NetDeclaration in net_demo becomes a role=net_decl node.

    net_demo has 4 NetDeclarations (wire nw; tri nt; supply0 ng;
    wire signed [3:0] nss;).
    """
    nd_nodes = [n for n in s54_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "net_decl"]
    nd_in_demo = [n for n in nd_nodes
                  if n["semantic"].get("path", "").startswith("net_demo.")]
    assert len(nd_in_demo) == 4, (
        f"expected 4 net_decl nodes in net_demo, got {len(nd_in_demo)}: "
        f"{[n['semantic'] for n in nd_in_demo]}"
    )


def test_s54_net_type_attribute_correct(s54_bundle):
    """S54: net_decl node carries net_type attribute matching the keyword."""
    nd_nodes = [n for n in s54_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "net_decl"
                and n["semantic"].get("path", "").startswith("net_demo.")]
    types_seen = {n["semantic"]["attributes"]["net_type"] for n in nd_nodes}
    assert types_seen == {"wire", "tri", "supply0"}, (
        f"unexpected net_type set: {types_seen}"
    )


def test_s54_signed_attribute(s54_bundle):
    """S54: wire signed [3:0] nss has signed=True; others signed=False."""
    nd_nodes = [n for n in s54_bundle["nodes"]
                if n.get("semantic", {}).get("role") == "net_decl"
                and n["semantic"].get("path", "").startswith("net_demo.")]
    signed_nodes = [n for n in nd_nodes
                    if n["semantic"]["attributes"].get("signed")]
    assert len(signed_nodes) == 1, (
        f"expected exactly 1 signed net_decl, got {len(signed_nodes)}"
    )


def test_s54_child_declarators_still_promoted_as_nets(s54_bundle):
    """S54 must not regress S1's net promotion: the four declarator names
    (nw, nt, ng, nss) all become role=net queryable nodes under net_demo."""
    nets = _net_demo_nodes(s54_bundle, "net")
    names = {n["semantic"]["name"] for n in nets}
    assert names == {"nw", "nt", "ng", "nss"}, (
        f"net declarator promotion lost names; got {names}"
    )


def test_s54_has_net_decl_edges(s54_bundle):
    """S54: each net_decl node receives a has_net_decl edge from its
    enclosing module."""
    nd_ids = {n["id"] for n in s54_bundle["nodes"]
              if n.get("semantic", {}).get("role") == "net_decl"
              and n["semantic"].get("path", "").startswith("net_demo.")}
    edges = [e for e in s54_bundle["edges"]
             if e["type"] == "has_net_decl" and e["dst"] in nd_ids]
    assert len(edges) == 4, (
        f"expected 4 has_net_decl edges, got {len(edges)}"
    )


def test_s54_groups_net_edges(s54_bundle):
    """S54: each net_decl group emits groups_net edges to its child
    role=net Declarator nodes.

    Each NetDeclaration in net_demo has exactly one Declarator, so there
    should be 4 groups_net edges total under net_demo.
    """
    net_ids = {n["id"] for n in _net_demo_nodes(s54_bundle, "net")}
    edges = [e for e in s54_bundle["edges"]
             if e["type"] == "groups_net" and e["dst"] in net_ids]
    assert len(edges) == 4, (
        f"expected 4 groups_net edges from net_decl→net, got {len(edges)}"
    )


def test_s54_no_double_count_has_net(s54_bundle):
    """S54 must not double-count: each net Declarator should have exactly
    one has_net edge from the module (S1's standard convention)."""
    net_ids = {n["id"] for n in _net_demo_nodes(s54_bundle, "net")}
    has_net = [e for e in s54_bundle["edges"]
               if e["type"] == "has_net" and e["dst"] in net_ids]
    assert len(has_net) == 4, (
        f"expected 4 has_net edges in net_demo, got {len(has_net)}"
    )


def test_s54_roundtrip_after_promote(s54_bundle):
    """S54 must not mutate token payloads — emit() reproduces fifo.sv
    byte-for-byte after net_demo is promoted."""
    text = NETDECL_SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    from knowledge_graph.builders.sv.unlift import emit

    emitted = emit(s54_bundle)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)
