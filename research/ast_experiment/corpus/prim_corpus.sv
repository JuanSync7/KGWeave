// S33 corpus: gate-level primitive instantiations.
//
// Covers four primitive types (and / or / buf with delay / not in
// multi-instance form). Mirrors how UDP-free RTL hand-instantiates
// gates at the leaf of a hierarchy.
module prim_demo (
    input  logic a,
    input  logic b,
    output logic out_and,
    output logic out_or,
    output logic out_buf,
    output logic n_a,
    output logic n_b
);
  and g_and (out_and, a, b);
  or  g_or  (out_or, a, b);
  buf #5 g_buf (out_buf, a);
  not g_not1 (n_a, a), g_not2 (n_b, b);
endmodule
