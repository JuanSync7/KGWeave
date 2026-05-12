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
endmodule

bind fifo fifo_asserts u_asserts(.clk(clk), .full(full), .push(push));
