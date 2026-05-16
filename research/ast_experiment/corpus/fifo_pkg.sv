package fifo_pkg;
  typedef enum logic [1:0] { EMPTY = 2'b00, NORMAL = 2'b01, FULL = 2'b10 } fifo_status_e;
  typedef struct packed {
    logic [7:0]  cmd;
    logic [31:0] payload;
    bit [3:0] flag_a, flag_b;
  } fifo_word_t;
  typedef union { int i; bit [31:0] b; } fifo_iu_t;
  typedef fifo_fwd_t;
  typedef enum fifo_fwd_enum_t;
  typedef struct fifo_fwd_struct_t;
  typedef union fifo_fwd_union_t;
  typedef class fifo_fwd_class_t;
  typedef interface class fifo_fwd_iface_class_t;
  parameter int DEFAULT_DEPTH = 8;
  nettype logic [7:0] data_net_t;
  nettype logic [7:0] resolved_net_t with fifo_resolver;
  export *::*;
endpackage
