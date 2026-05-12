module top (
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

endmodule
