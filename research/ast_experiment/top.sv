module top (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        push,
    input  logic        pop,
    input  logic [31:0] din,
    output logic [31:0] dout,
    output logic        full,
    output logic        empty
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

endmodule
