// S86 corpus: InterfacePortHeader — ANSI module ports declared with an
// interface type, optionally modport-qualified.
//
// Exercises three header shapes:
//   1. ``fifo_if.dut a`` — interface name + ``.dut`` modport
//   2. ``fifo_if.consumer b`` — interface name + ``.consumer`` modport
//   3. ``interface c`` — generic ``interface`` keyword form (no name, no
//      modport — InterfacePortHeader with the InterfaceKeyword variant).
//
// The leaf module body is empty on purpose: the port headers are the only
// semantic content S86 needs.

module iface_port_dut (
    fifo_if.dut       a,
    fifo_if.consumer  b,
    interface         c
);
endmodule
