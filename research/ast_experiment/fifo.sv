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

    logic [WIDTH-1:0] mem [DEPTH];
    logic [$clog2(DEPTH):0] wr_ptr;
    logic [$clog2(DEPTH):0] rd_ptr;
    logic [$clog2(DEPTH):0] count;

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
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (pop && !empty) begin
                rd_ptr <= rd_ptr + 1'b1;
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
