package cls_pkg;

  virtual class base_xact;
    int id;
  endclass

  class data_xact extends base_xact;
    bit [7:0] payload;
    static int instance_count = 0;
    rand int rnd_field;
    int a, b, c;
    constraint c_payload_nonzero { payload != 0; }
    constraint c_payload_range { payload inside {[1:200]}; }
    static constraint c_static_demo { 1 == 1; }
    extern constraint c_external;
    function new();
      instance_count++;
    endfunction
    virtual function void print();
      $display("data_xact id=%0d", id);
    endfunction
  endclass

  interface class printable;
    pure virtual function void print();
  endclass

  class para_xact #(type T = int);
    T value;
  endclass

  // S48 corpus: multi-assignment form — one TypeParameterDeclaration with
  // two TypeAssignment children: parameter type A = int, B = bit;
  class multi_type_xact #(type A = int, B = bit);
    A a_val;
    B b_val;
  endclass

  class printable_xact extends base_xact implements printable;
    virtual function void print();
    endfunction
  endclass

endpackage

// S52 corpus: inline randomize() with { ... } — ConstraintBlock appears
// directly inside ArrayOrRandomizeMethodExpression (not inside a named
// ConstraintDeclaration).  Two inline blocks so the byte-offset uniqueness
// of __inline_constraint_<offset>__ can be verified by tests.
module s52_inline_top;
  initial begin
    automatic cls_pkg::data_xact t = new;
    int ok;
    ok = t.randomize() with { payload < 100; };
    ok = t.randomize() with { payload > 10; rnd_field < 50; };
  end
endmodule
