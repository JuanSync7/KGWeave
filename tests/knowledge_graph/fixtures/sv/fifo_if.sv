interface fifo_if #(parameter int WIDTH = 32) (input logic clk, input logic rst_n);
    logic                push, pop, full, empty;
    logic [WIDTH-1:0]    din, dout;
    modport producer (input  full, empty, dout, output push, din);
    modport consumer (input  full, empty, dout, output pop);
    modport dut      (input  push, pop, din, output full, empty, dout);
endinterface
