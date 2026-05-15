module fifo
    import fifo_pkg::*;
#(
    parameter int DEPTH = 8,
    parameter int WIDTH = 32
) (
    input  logic              clk,
    input  logic              rst_n,
    input  logic              push,
    input  logic              pop,
    input  logic [WIDTH-1:0]  din,
    output logic [WIDTH-1:0]  dout,
    output logic              full,
    output logic              empty,
    output fifo_status_e      status
);

    import fifo_pkg::FULL;

    logic [WIDTH-1:0] mem [DEPTH];
    logic [$clog2(DEPTH):0] wr_ptr;
    logic [$clog2(DEPTH):0] rd_ptr;
    logic [$clog2(DEPTH):0] count;

    function automatic logic [$clog2(DEPTH):0] next_ptr(logic [$clog2(DEPTH):0] p);
        next_ptr = p + 1'b1;
    endfunction

    assign full  = (count == DEPTH);
    assign empty = (count == 0);
    assign dout  = mem[rd_ptr[$clog2(DEPTH)-1:0]];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
            count  <= '0;
        end else begin
            if (push && !full) begin
                mem[wr_ptr[$clog2(DEPTH)-1:0]] <= din;
                wr_ptr <= next_ptr(wr_ptr);
            end
            if (pop && !empty) begin
                rd_ptr <= next_ptr(rd_ptr);
            end
            case ({push && !full, pop && !empty})
                2'b10: count <= count + 1'b1;
                2'b01: count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end

    always_comb begin
        if (full)        status = FULL;
        else if (empty)  status = EMPTY;
        else             status = NORMAL;
    end

endmodule

// S34 corpus: generic always @(...) blocks — non-FF, non-comb, non-latch.
// Two variants exercised:
//   1. always @(posedge clk) — edge-sensitive sensitivity list
//   2. always @(a or b)      — level-sensitive sensitivity list
module always_demo (
    input  logic clk,
    input  logic a,
    input  logic b,
    output logic q,
    output logic r
);
    // Variant 1: posedge-only (generic always, not always_ff)
    always @(posedge clk) begin
        q <= a;
    end

    // Variant 2: level-sensitive (a or b)
    always @(a or b) begin
        r = a & b;
    end
endmodule

// S35 corpus: always_latch block — inferred latch (no sensitivity list).
// Two signals exercised:
//   latch_out — driven when en is high, reads latch_in
//   latch_sel — driven from a conditional reading both latch_in and b
module latch_demo (
    input  logic en,
    input  logic latch_in,
    input  logic b,
    output logic latch_out,
    output logic latch_sel
);
    always_latch begin
        if (en) begin
            latch_out = latch_in;
            latch_sel = latch_in & b;
        end
    end
endmodule
