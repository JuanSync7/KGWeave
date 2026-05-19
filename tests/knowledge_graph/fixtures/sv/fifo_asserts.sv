// Out-of-source assertion module bound into `fifo`.
//
// Demonstrates the SystemVerilog `bind` directive: `fifo_asserts` is
// attached to every instance of `fifo` without `fifo.sv` referencing it.
// EDA tools resolve this during elaboration; the AST-experiment promotes
// it to a `bound_into` semantic edge in S13.

module fifo_asserts(
    input logic clk,
    input logic full,
    input logic push
);
    // S39 — default disable condition for all concurrent assertions in this
    // scope. ``rst_n`` is referenced in the iff expression; the rule must
    // emit a ``reads`` edge from the default_disable node to the port.
    logic rst_n;
    default disable iff (!rst_n);

    // Placeholder assertions — body is intentionally empty for the
    // round-trip corpus. The semantic edge is independent of contents.
    // S57 — LocalVariableDeclaration inside property/sequence bodies.
    // pyslang surfaces these as LocalVariableDeclarationSyntax (distinct
    // from procedural-scope DataDeclarationSyntax). Each declarator inside
    // a single ``int a, b;`` form fans out to its own role=local_var node.
    property p_push_implies_not_full;
        int hits = 0;
        bit [7:0] mask, scratch;
        @(posedge clk) push |-> !full;
    endproperty

    sequence s_push_then_full;
        int seen = 0;
        @(posedge clk) push ##[1:2] full;
    endsequence

    // S77 — AssertionItemPort: ports declared on a parameterised property /
    // sequence / let. Each ``input bit clk`` / ``logic sig`` / ``int n``
    // entry parses as an AssertionItemPortSyntax inside the
    // AssertionItemPortListSyntax wrapper. S77 promotes each to role=
    // assertion_item_port with direction/data_type/local/name attrs and a
    // ``has_assertion_item_port`` edge from the enclosing property /
    // sequence / let.
    property p_with_ports(logic sig, int n);
        @(posedge clk) sig |-> ##n !sig;
    endproperty

    sequence s_with_ports(logic a, logic b);
        @(posedge clk) a ##1 b;
    endsequence

    // S77 — port with explicit ``local input`` direction qualifier. Per
    // LRM 16.8, only ``local`` and (for properties) ``input``-style
    // directions are accepted on assertion item ports; ``let`` ports do
    // not allow a direction keyword.
    property p_dir_ports(local input logic sig, logic gate);
        @(posedge clk) gate |-> sig;
    endproperty

    // S18 — clocking blocks. ``cb_fifo`` is an ordinary clocking block;
    // ``cb_default`` exercises the ``default clocking`` form. Clocking items
    // (input/output direction declarations) stay BLOB — only the
    // ClockingDeclaration itself is promoted.
    clocking cb_fifo @(posedge clk);
        input  full, push;
        output #1 rst_n;
    endclocking

    default clocking cb_default @(posedge clk);
        default input #1step output #2;
    endclocking

    // S40 — DefaultClockingReference: ``default clocking <name>;`` selects
    // which named clocking block is the implicit default for the scope.
    // This is an edge-only kind (no independent identity); S40 emits a
    // ``default_clocking`` edge from the enclosing module to the target
    // clocking block. Resolved via name_index; fallback to _unresolved.<name>.
    default clocking cb_fifo;

    // S71 — module-scope immediate assertion. Parses as an
    // ``ImmediateAssertionMember`` wrapping the inner
    // ``ImmediateAssertStatement``; S71 owns the wrapper (stub only) and
    // S17 promotes the inner. Exactly one assertion node must result.
    a_imm_modscope: assert (!(push && full));

    // S16 — concurrent assertion use sites. Labeled top-level forms exercise
    // the ConcurrentAssertionMember wrapper path; the unlabeled cover sits
    // alongside to confirm synthetic-label fallback.
    a_no_push_when_full: assert property (@(posedge clk) full |-> !push);
    a_push_implies_seq: assume property (@(posedge clk) push |-> !full);
    c_push_event: cover property (@(posedge clk) push);
    cover property (@(posedge clk) push |-> !full);

    // S17 — immediate assertions inside a procedural context. Per LRM these
    // cannot sit at module top level (except via the ImmediateAssertionMember
    // wrapper); a labeled + unlabeled + deferred (#0) + deferred (final) +
    // assume + cover form covers the kind grid. We use ``initial`` rather
    // than ``always_comb`` so the corpus does not perturb existing query
    // tests that count always_comb blocks across the multi-file fixture.
    initial begin
        a_imm_no_push_when_full: assert (!(push && full));
        c_imm_push: cover (push);
        a_imm_deferred_zero: assert #0 (!(push && full));
        a_imm_deferred_final: assert final (!(push && full));
        assume (clk === 1'b0 || clk === 1'b1);
    end

    // S22 — covergroup declarations. ``cg_fifo`` carries a clocking event
    // (``@(posedge clk)``); ``cg_simple`` has none. S23 — coverpoint and
    // cross sub-elements are promoted. S41 — CoverageBins declarations inside
    // coverpoints are promoted with role=coverage_bins and bins_kind attr.
    covergroup cg_fifo @(posedge clk);
        cp_full: coverpoint full;
        cp_push: coverpoint push {
            bins low    = {[0:3]};
            bins high[] = {[4:7]};
            illegal_bins bad = {255};
        }
        cp_push_full: coverpoint {push, full};
        cx_push_full: cross cp_push, cp_full;
    endgroup

    covergroup cg_simple;
        cp_full: coverpoint full;
    endgroup
endmodule

// S19 — procedural continuous assign/deassign. These are statement-level
// constructs inside an always block (distinct from S2's module-level
// continuous assign). The corpus must include a writable variable that
// is the target of both forms so the LHS-extraction path is exercised.
module proc_assign_demo (
    input  logic       clk,
    input  logic       load,
    input  logic [7:0] din,
    output logic [7:0] q
);
    logic [7:0] r;
    always @(posedge clk) begin
        if (load) assign r = din;
        else      deassign r;
    end
    assign q = r;
endmodule

// S20 — procedural force/release. Like S19's assign/deassign but stronger:
// `force` overrides even continuous drivers, and `release` lifts the override.
// pyslang surfaces these as ProceduralAssignStatementSyntax /
// ProceduralDeassignStatementSyntax classes — discriminated only by
// SyntaxKind.{ProceduralForceStatement,ProceduralReleaseStatement}.
module force_release_demo (
    input  logic       clk,
    input  logic       dbg_override,
    output logic [7:0] dbg_q
);
    logic [7:0] r;
    always @(posedge clk) begin
        if (dbg_override) force r = 8'hAA;
        else              release r;
    end
    assign dbg_q = r;
endmodule

// S21 — named event trigger statements. ``-> ev`` is the blocking form,
// ``->> ev`` is the nonblocking form. pyslang surfaces both as
// EventTriggerStatementSyntax — discriminated only by SyntaxKind
// {BlockingEventTriggerStatement, NonblockingEventTriggerStatement}.
module event_trigger_demo (input logic clk);
    event ev_done, ev_ready;
    always @(posedge clk) begin
        -> ev_done;
        ->> ev_ready;
    end
endmodule

// S42 — LetDeclaration: compile-time macro-like substitution. ``let nonzero(x)
// = x != 0;`` declares a single-port let that can be used inside assertion
// expressions. The rule promotes it with role=let_decl, a has_let edge from
// the enclosing module, and registers the qualified path in the name_index so
// callers referencing the let can resolve it.
module let_decl_demo (
    input logic clk,
    input logic [7:0] data
);
    let nonzero(x) = x != 0;
    let in_range(a, b) = a < b;
    let always_true() = 1;
    // S77 — let with a default-valued AssertionItemPort. ``let`` ports do
    // not accept a direction keyword (LRM forbids it); the directional
    // case is covered via the parameterised sequence ``s_dir_ports`` in
    // module ``fifo_asserts`` above.
    let bounded(int x, int hi = 8) = x < hi;
endmodule

bind fifo fifo_asserts u_asserts(.clk(clk), .full(full), .push(push));

// S61 — explicit BindTargetList: this bind directive applies only to the
// named instances ``u_fifo_a`` and ``u_fifo_b`` of module ``fifo``, not to
// every instance of ``fifo``. The ``: u_fifo_a, u_fifo_b`` clause is the
// BindTargetListSyntax — a connector child of BindDirective listing the
// specific instance names. ``ghost_u`` exercises the unresolved fallback.
bind fifo : u_fifo_a, u_fifo_b, ghost_u fifo_asserts u_targeted(.clk(clk), .full(full), .push(push));
