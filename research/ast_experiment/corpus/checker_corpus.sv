// S28 corpus: CheckerDeclaration + CheckerInstantiation.
// Exercises a checker definition with internal property + assertion,
// and a module that instantiates it.

module checker_corpus_top (input logic clk, input logic a, input logic b);
  c_mutex u_mutex (.clk(clk), .x(a), .y(b));
endmodule

checker c_mutex (input clk, input x, input y);
  default clocking @(posedge clk); endclocking
  property p_mutex;
    !(x && y);
  endproperty
  a_mutex: assert property (p_mutex);
endchecker
