// S47 corpus: timeunit / timeprecision directives inside a module.
// Both the keyword-separated form (two statements) and the combined
// timeunit <unit> / <prec>; form are exercised here and in fifo_pkg.sv.
//
// S48 corpus: TypeParameterDeclaration — parameter type DATA_T = logic [7:0]
// exercises the single-assignment form with a default type.
module fifo
    import fifo_pkg::*;
#(
    parameter int DEPTH = 8,
    parameter int WIDTH = 32,
    parameter type DATA_T = logic [7:0]
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

    timeunit 1ns;
    timeprecision 1ps;

    import fifo_pkg::FULL;
    // S50 corpus: multi-item PackageImportDeclaration — two PackageImportItem
    // children in one declaration, exercising the per-item imports_item edge.
    import fifo_pkg::EMPTY, fifo_pkg::NORMAL;

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

// S38 corpus: genvar declaration (single and multi-identifier) + for-generate.
// Exercises:
//   genvar i;            — single genvar
//   genvar j, k;         — multi-genvar (two identifiers in one declaration)
//   for (i = 0; ...) begin : g_ent  — for-generate referencing i
module genvar_demo #(parameter int N = 4) ();
    genvar i;
    genvar j, k;
    for (i = 0; i < N; i = i + 1) begin : g_ent
    end
endmodule

// S44 corpus: DPI import declarations.
// Exercises the four key variants:
//   1. import "DPI-C" function int c_compute(input int x)  — function, DPI-C spec
//   2. import "DPI-C" task c_log(input int level)          — task, DPI-C spec
//   3. import "DPI" function void dpi_reset()              — function, DPI spec
//
// S45 corpus: DPI export declarations (export "DPI-C" function|task <name> ;).
// Two variants exercised:
//   1. export "DPI-C" function sv_compute  — re-exports a module-local SV function
//   2. export "DPI-C" task sv_task         — exports a task (resolves to _unresolved)
// sv_compute is defined as a regular SV function so the edge resolves via name_index.
// sv_task has no body in this scope so the edge emits _unresolved.sv_task.
module dpi_demo ();
    import "DPI-C" function int c_compute(input int x);
    import "DPI-C" task c_log(input int level);
    import "DPI" function void dpi_reset();

    function automatic int sv_compute(input int x);
        sv_compute = x * 2;
    endfunction

    export "DPI-C" function sv_compute;
    export "DPI-C" task sv_task;
endmodule

// S46 corpus: net alias declaration (bidirectional equivalence, SV §10.11).
// Three signals form one alias chain: alias a = b = c;
// Expected edges: a aliases b, b aliases c  (consecutive-pairs convention).
// The three logic declarations ensure name_index has entries for a, b, c.
module alias_demo;
    logic a, b, c;
    alias a = b = c;
endmodule

// S54 corpus: NetDeclaration variants exercising net_type and signing.
// Expected nodes:
//   - net_decl group nodes (one per NetDeclaration statement) carrying
//     {net_type, signed} attrs.
//   - role="net" Declarator children promoted under each group, plus
//     has_net edges to the enclosing module (same convention as S1).
module net_demo;
    wire nw;
    tri  nt;
    supply0 ng;
    wire signed [3:0] nss;
endmodule

// S55 corpus: non-ANSI module with PortDeclarations in the body.
// Module header carries an ImplicitNonAnsiPort list (a, b, c, d, e, f); the
// PortDeclarations in the body bind each name to a direction + type. S55
// promotes each Declarator under a PortDeclarationSyntax as role="port" with
// the direction attribute lifted from the parent header (Variable/Net port
// header). Multiple declarators per PortDeclaration are supported
// (``output e, f``).
module nonansi_demo(a, b, c, d, e, f);
    input  a;
    output [7:0] b;
    inout  wire c;
    input  signed [3:0] d;
    output e, f;
endmodule

// S64 corpus: ANSI module header with ExplicitAnsiPort entries.
// Each ``.name(expr)`` form in the ANSI port list — prefixed with a direction
// keyword — parses as SyntaxKind.ExplicitAnsiPort (sibling of S1's
// ImplicitAnsiPort). The port name is the identifier after the dot; the
// optional connect expression remaps the public name onto an internal signal.
// The empty-connect form ``.pd()`` is legal SV (declares a port with no
// internal connection) and must not crash the rule.
module ansi_explicit_demo(
    input  .pa(x),
    output .pb(y[3:0]),
    inout  .pc(z),
    input  .pd()
);
    wire x, z;
    wire [3:0] y;
endmodule

// S65 corpus: legacy Verilog-2001 non-ANSI explicit port form. Each
// ``.name(expr)`` inside a NonAnsiPortList (no direction keyword in the
// header — directions arrive via separate input/output statements in the
// body) parses as SyntaxKind.ExplicitNonAnsiPort. The explicit empty-connect
// ``.b()`` form is also ExplicitNonAnsiPort (pyslang surfaces it with no
// PortReference child); the bare ``.b`` shorthand is intentionally NOT used
// here because the structural round-trip currently normalises it to
// ``.b()`` — a known pre-existing lift/unlift limitation independent of
// S65. Sibling of S1's ImplicitAnsiPort and S64's ExplicitAnsiPort;
// direction lives on the body PortDeclaration (S55).
module legacy_explicit_demo(.a(p), .b());
    input p, b;
endmodule

// S66 corpus: legacy Verilog-2001 non-ANSI implicit port form. Each bare
// name in the NonAnsiPortList parses as SyntaxKind.ImplicitNonAnsiPort with
// a PortReferenceSyntax child carrying the identifier; directions/types
// arrive via separate input/output statements in the body (S55). The
// concatenation entry ``{x, y}`` parses as ImplicitNonAnsiPort wrapping a
// PortConcatenationSyntax — S66 skips emission for the concatenation form
// (no single port name to key on); S68 promotes the PortConcatenation
// itself as role=port_concat at the synthetic path
// ``legacy_implicit_demo.__port_concat_0__`` and emits groups_port_ref
// edges to its constituent PortReference members (x, y). Sibling of S1
// ImplicitAnsiPort, S64 ExplicitAnsiPort, S65 ExplicitNonAnsiPort.
module legacy_implicit_demo(a, b, {x, y});
    input a;
    output b;
    input x, y;
endmodule
