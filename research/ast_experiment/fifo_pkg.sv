package fifo_pkg;
  typedef enum logic [1:0] { EMPTY = 2'b00, NORMAL = 2'b01, FULL = 2'b10 } fifo_status_e;
  parameter int DEFAULT_DEPTH = 8;
endpackage
