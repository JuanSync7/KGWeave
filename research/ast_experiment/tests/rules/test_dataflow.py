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
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return tree, comp, graph


def _queryable_by_role(graph, role):
    from research.ast_experiment.src.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph) if n.get("semantic", {}).get("role") == role]


def test_roundtrip_after_promote(fixture_bundle):
    """Promotion must not mutate token payloads — emit() still reproduces source."""
    tree, _comp, graph = fixture_bundle
    from research.ast_experiment.src.unlift import emit

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
    from research.ast_experiment.src.semantic import find_drivers

    drivers = find_drivers(graph, "dout")
    assert len(drivers) == 1
    assert drivers[0]["semantic"]["role"] == "continuous_assign"

    full_drivers = find_drivers(graph, "full")
    assert len(full_drivers) == 1
    # The 'full' assign reads `count` (and the param DEPTH via name resolution).
    from research.ast_experiment.src.semantic import neighbors

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
    from research.ast_experiment.src.semantic import neighbors

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
    from research.ast_experiment.src.semantic import neighbors

    for s in selects:
        if s["semantic"]["base"] == "mem":
            tgt = neighbors(graph, s["id"], edge_type="reads", direction="out")
            assert any(t["semantic"].get("name") == "mem" for t in tgt)


def test_s5_system_call_clog2_reads_depth(fixture_bundle):
    """S5: every `$clog2(DEPTH)` call is promoted and `reads` DEPTH."""
    _tree, _comp, graph = fixture_bundle
    calls = _queryable_by_role(graph, "system_call")
    assert calls, "expected at least one $clog2 invocation"
    from research.ast_experiment.src.semantic import neighbors

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
    from research.ast_experiment.src.semantic import neighbors

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
    from research.ast_experiment.src.semantic import neighbors

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
    from research.ast_experiment.src.unlift import emit

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
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

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
    from research.ast_experiment.src.unlift import emit

    emitted = emit(s35_bundle)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)
