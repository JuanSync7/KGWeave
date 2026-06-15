// Tiny leaf module used by ``top`` to exercise S69 ordered port connections
// (positional ``module u_inst(a, b, c);`` form). Port order = clk, rst, q.
module dut_positional (
    input  logic clk,
    input  logic rst,
    output logic q
);
    assign q = 1'b0;
endmodule

module top #(
    parameter int NUM_FIFOS = 2
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        push,
    input  logic        pop,
    input  logic [31:0] din,
    output logic [31:0] dout,
    output logic        full,
    output logic        empty,
    input  logic        push_a,
    input  logic        pop_a,
    input  logic [31:0] din_a,
    output logic [31:0] dout_a,
    output logic        full_a,
    output logic        empty_a,
    input  logic        push_b,
    input  logic        pop_b,
    input  logic [7:0]  din_b,
    output logic [7:0]  dout_b,
    output logic        full_b,
    output logic        empty_b
);

    fifo u_fifo (
        .clk   (clk),
        .rst_n (rst_n),
        .push  (push),
        .pop   (pop),
        .din   (din),
        .dout  (dout),
        .full  (full),
        .empty (empty)
    );

    fifo #(.DEPTH(16), .WIDTH(32)) u_fifo_a (
        .clk   (clk),
        .rst_n (rst_n),
        .push  (push_a),
        .pop   (pop_a),
        .din   (din_a),
        .dout  (dout_a),
        .full  (full_a),
        .empty (empty_a)
    );

    fifo_if #(.WIDTH(32)) u_if (
        .clk   (clk),
        .rst_n (rst_n)
    );

    fifo #(.DEPTH(8), .WIDTH(8)) u_fifo_b (
        .clk   (clk),
        .rst_n (rst_n),
        .push  (push_b),
        .pop   (pop_b),
        .din   (din_b),
        .dout  (dout_b),
        .full  (full_b),
        .empty (empty_b)
    );

    // S69 — positional (ordered) port connection form. Sibling of the S6
    // named ``.port(net)`` form above. Each entry in the connection list
    // is matched to the dut's declared ports in declaration order.
    dut_positional u_pos (clk, rst_n, push);

    defparam u_fifo.DEPTH = 8;

    generate
        for (genvar i = 0; i < NUM_FIFOS; i++) begin: gen_fifos
            fifo u_fifo_gen (
                .clk   (clk),
                .rst_n (rst_n),
                .push  (push),
                .pop   (pop),
                .din   (din),
                .dout  (),
                .full  (),
                .empty (),
                .status()
            );
        end
    endgenerate

endmodule
