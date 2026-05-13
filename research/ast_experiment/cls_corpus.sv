package cls_pkg;

  virtual class base_xact;
    int id;
  endclass

  class data_xact extends base_xact;
    bit [7:0] payload;
  endclass

  interface class printable;
    pure virtual function void print();
  endclass

  class para_xact #(type T = int);
    T value;
  endclass

endpackage
