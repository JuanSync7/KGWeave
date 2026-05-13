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
    // Placeholder assertions — body is intentionally empty for the
    // round-trip corpus. The semantic edge is independent of contents.
    property p_push_implies_not_full;
        @(posedge clk) push |-> !full;
    endproperty

    sequence s_push_then_full;
        @(posedge clk) push ##[1:2] full;
    endsequence

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
endmodule

bind fifo fifo_asserts u_asserts(.clk(clk), .full(full), .push(push));
