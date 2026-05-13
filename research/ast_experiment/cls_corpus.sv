package cls_pkg;

  virtual class base_xact;
    int id;
  endclass

  class data_xact extends base_xact;
    bit [7:0] payload;
    static int instance_count = 0;
    rand int rnd_field;
    int a, b, c;
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

  class printable_xact extends base_xact implements printable;
    virtual function void print();
    endfunction
  endclass

endpackage
