// of_type for NETS and PARAMS (the declarator-sibling case).
//
// For a port, the declared type lives inside the port's own header subtree
// (covered by the of_type port case). For a net or parameter, pyslang parses
// the type as a *sibling* of the declarator under the enclosing
// DataDeclaration / ParameterDeclaration — so resolving it needs a parent
// lookup, not a descendant scan. This module exercises that path.
//
// It imports fifo_pkg so the user-defined type names resolve by bare name;
// package-qualified references (`fifo_pkg::fifo_status_e`) are a separate,
// still-open partial (ScopedName resolution), deliberately not used here.
module of_type_demo
    import fifo_pkg::*;
();
    fifo_status_e cur_status;          // net typed by an enum typedef
    fifo_word_t   cur_word, prev_word; // two declarators share one struct type
    localparam fifo_status_e INIT_ST = EMPTY;  // param typed by an enum typedef
    logic [7:0]   plain_net;           // built-in type → NO of_type edge
endmodule

// ScopedName (`pkg::T`) — net/param typed by a package-qualified type, with
// NO `import`, so resolution must parse the `pkg::T` ScopedName (the type is
// the LAST segment, not the first) rather than fall back to bare-name-via-
// import. The NamedType wraps a ScopedNameSyntax whose first identifier is the
// package and whose last is the type.
module scoped_type_demo ();
    fifo_pkg::fifo_status_e scoped_status;                 // net, scoped type
    localparam fifo_pkg::fifo_status_e SCOPED_INIT = fifo_pkg::EMPTY;  // param
endmodule
