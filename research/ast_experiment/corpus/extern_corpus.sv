extern module ext_mod #(parameter int W = 8) (input logic clk, output logic [W-1:0] q);
extern interface ext_if (input logic clk);
extern program ext_prog ();

module ext_mod #(parameter int W = 8) (input logic clk, output logic [W-1:0] q);
  assign q = '0;
endmodule

interface ext_if (input logic clk);
  logic ready;
endinterface

program ext_prog ();
  initial $display("ext_prog");
endprogram
