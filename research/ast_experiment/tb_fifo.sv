module tb_fifo;
    logic        clk;
    logic        rst_n;
    logic        push;
    logic        pop;
    logic [31:0] din;
    logic [31:0] dout;
    logic        full;
    logic        empty;
    logic        push_a;
    logic        pop_a;
    logic [31:0] din_a;
    logic [31:0] dout_a;
    logic        full_a;
    logic        empty_a;
    logic        push_b;
    logic        pop_b;
    logic [7:0]  din_b;
    logic [7:0]  dout_b;
    logic        full_b;
    logic        empty_b;

    top u_dut (
        .clk    (clk),
        .rst_n  (rst_n),
        .push   (push),
        .pop    (pop),
        .din    (din),
        .dout   (dout),
        .full   (full),
        .empty  (empty),
        .push_a (push_a),
        .pop_a  (pop_a),
        .din_a  (din_a),
        .dout_a (dout_a),
        .full_a (full_a),
        .empty_a(empty_a),
        .push_b (push_b),
        .pop_b  (pop_b),
        .din_b  (din_b),
        .dout_b (dout_b),
        .full_b (full_b),
        .empty_b(empty_b)
    );

    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end

    initial begin
        rst_n = 0;
        push  = 0;
        pop   = 0;
        din   = 32'h0;
        #20 rst_n = 1;
        #10 push = 1; din = 32'hCAFEBABE;
        #10 push = 0;
        #10 pop  = 1;
        #10 pop  = 0;
        $display("dout=%h full=%b empty=%b", dout, full, empty);
        #20 $finish;
    end

endmodule
