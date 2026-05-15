package fifo_pkg;
  typedef enum logic [1:0] { EMPTY = 2'b00, NORMAL = 2'b01, FULL = 2'b10 } fifo_status_e;
  typedef struct packed {
    logic [7:0]  cmd;
    logic [31:0] payload;
  } fifo_word_t;
  typedef union { int i; bit [31:0] b; } fifo_iu_t;
  typedef fifo_fwd_t;
  parameter int DEFAULT_DEPTH = 8;
  export *::*;
endpackage
