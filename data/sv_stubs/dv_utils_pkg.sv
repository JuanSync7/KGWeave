// Empty stub for slang elaboration of OpenTitan DV files.
// KGWeave does not validate UVM behavior — it only needs the symbols to
// resolve so covergroup definitions are reachable. The real dv_utils_pkg
// transitively imports uvm_pkg and bus_params_pkg; none of those symbols
// are used inside the AES covergroup bodies. Replace with the real package
// if running a UVM-aware compile.
package dv_utils_pkg;
endpackage
