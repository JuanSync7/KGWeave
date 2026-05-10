// Tiny synthetic SoC for the KG demo: CPU + ALU + memory controller
// connected through a small AXI-like bus. ~20 entities, hierarchical.

module alu (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic [31:0] operand_a_i,
    input  logic [31:0] operand_b_i,
    input  logic [3:0]  operator_i,
    output logic [31:0] result_o,
    output logic        zero_o
);
    logic [31:0] sum;
    logic [31:0] diff;
    assign sum  = operand_a_i + operand_b_i;
    assign diff = operand_a_i - operand_b_i;
    assign result_o = (operator_i == 4'd0) ? sum : diff;
    assign zero_o   = (result_o == 32'd0);
endmodule

module regfile #(
    parameter int unsigned NumRegs = 32
) (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic [4:0]  raddr_a_i,
    input  logic [4:0]  raddr_b_i,
    input  logic [4:0]  waddr_i,
    input  logic [31:0] wdata_i,
    input  logic        we_i,
    output logic [31:0] rdata_a_o,
    output logic [31:0] rdata_b_o
);
    logic [31:0] mem [NumRegs];
    assign rdata_a_o = mem[raddr_a_i];
    assign rdata_b_o = mem[raddr_b_i];
endmodule

module cpu_core (
    input  logic        clk_i,
    input  logic        rst_ni,
    output logic [31:0] data_addr_o,
    output logic        data_we_o,
    output logic [31:0] data_wdata_o,
    input  logic [31:0] data_rdata_i
);
    logic [31:0] alu_result;
    logic [31:0] reg_a;
    logic [31:0] reg_b;
    logic        alu_zero;

    alu u_alu (
        .clk_i      (clk_i),
        .rst_ni     (rst_ni),
        .operand_a_i(reg_a),
        .operand_b_i(reg_b),
        .operator_i (4'd0),
        .result_o   (alu_result),
        .zero_o     (alu_zero)
    );

    regfile #(.NumRegs(32)) u_regfile (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        .raddr_a_i(5'd0),
        .raddr_b_i(5'd1),
        .waddr_i  (5'd2),
        .wdata_i  (alu_result),
        .we_i     (1'b1),
        .rdata_a_o(reg_a),
        .rdata_b_o(reg_b)
    );

    assign data_addr_o  = alu_result;
    assign data_we_o    = 1'b1;
    assign data_wdata_o = alu_result;
endmodule

module mem_ctrl (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic [31:0] addr_i,
    input  logic        we_i,
    input  logic [31:0] wdata_i,
    output logic [31:0] rdata_o
);
    logic [31:0] cell;
    assign rdata_o = cell;
endmodule

module soc_top (
    input logic clk_i,
    input logic rst_ni
);
    logic [31:0] cpu_addr;
    logic        cpu_we;
    logic [31:0] cpu_wdata;
    logic [31:0] cpu_rdata;

    cpu_core u_cpu (
        .clk_i        (clk_i),
        .rst_ni       (rst_ni),
        .data_addr_o  (cpu_addr),
        .data_we_o    (cpu_we),
        .data_wdata_o (cpu_wdata),
        .data_rdata_i (cpu_rdata)
    );

    mem_ctrl u_mem (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),
        .addr_i (cpu_addr),
        .we_i   (cpu_we),
        .wdata_i(cpu_wdata),
        .rdata_o(cpu_rdata)
    );
endmodule
