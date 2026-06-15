# Fifo design notes

The `fifo` module is parameterised over `WIDTH` and `DEPTH`.
See also the supporting package `fifo_pkg` for shared types.

## Usage

Wire the design like this:

```systemverilog
fifo #(.WIDTH(8), .DEPTH(16)) u_fifo (.clk(clk), .rst_n(rst_n));
```

The block above mentions `fifo` again; the connector treats
each occurrence as a distinct reference site.

## Non-references

We also mention `nonexistent_module` which has no SV counterpart;
the connector must not synthesize an edge for it.
