# Worked example: simple push/pop FIFO — what is node / edge / blob

## The source

```systemverilog
module fifo #(
    parameter int DEPTH = 8,
    parameter int WIDTH = 32
) (
    input  logic              clk,
    input  logic              rst_n,
    input  logic              push,
    input  logic              pop,
    input  logic [WIDTH-1:0]  din,
    output logic [WIDTH-1:0]  dout,
    output logic              full,
    output logic              empty
);

    logic [WIDTH-1:0] mem [DEPTH];
    logic [$clog2(DEPTH):0] wr_ptr, rd_ptr;
    logic [$clog2(DEPTH):0] count;

    assign full  = (count == DEPTH);
    assign empty = (count == 0);
    assign dout  = mem[rd_ptr[$clog2(DEPTH)-1:0]];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
            count  <= '0;
        end else begin
            if (push && !full) begin
                mem[wr_ptr[$clog2(DEPTH)-1:0]] <= din;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (pop && !empty) begin
                rd_ptr <= rd_ptr + 1'b1;
            end
            case ({push && !full, pop && !empty})
                2'b10: count <= count + 1'b1;
                2'b01: count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end

endmodule
```

---

## Graph view

### Nodes (graph-visible — small, typed, traversable)

| id              | type                | name      |
|-----------------|---------------------|-----------|
| n.mod.fifo      | module              | fifo      |
| n.param.depth   | parameter           | DEPTH     |
| n.param.width   | parameter           | WIDTH     |
| n.port.clk      | port (input)        | clk       |
| n.port.rst_n    | port (input)        | rst_n     |
| n.port.push     | port (input)        | push      |
| n.port.pop      | port (input)        | pop       |
| n.port.din      | port (input)        | din       |
| n.port.dout     | port (output)       | dout      |
| n.port.full     | port (output)       | full      |
| n.port.empty    | port (output)       | empty     |
| n.net.mem       | net (array)         | mem       |
| n.net.wr_ptr    | net                 | wr_ptr    |
| n.net.rd_ptr    | net                 | rd_ptr    |
| n.net.count     | net                 | count     |
| n.assign.full   | continuous_assign   | —         |
| n.assign.empty  | continuous_assign   | —         |
| n.assign.dout   | continuous_assign   | —         |
| n.always.seq    | always_ff           | —         |
| n.case.cnt      | case_stmt           | —         |

### Edges (typed relationships — this is what queries walk)

```
n.mod.fifo  --has_param-->  n.param.depth, n.param.width
n.mod.fifo  --has_port-->   n.port.clk, n.port.rst_n, n.port.push, n.port.pop,
                            n.port.din, n.port.dout, n.port.full, n.port.empty
n.mod.fifo  --has_net-->    n.net.mem, n.net.wr_ptr, n.net.rd_ptr, n.net.count

# Continuous assigns
n.assign.full   --drives-->  n.port.full
n.assign.full   --reads-->   n.net.count
n.assign.full   --reads-->   n.param.depth

n.assign.empty  --drives-->  n.port.empty
n.assign.empty  --reads-->   n.net.count

n.assign.dout   --drives-->  n.port.dout
n.assign.dout   --reads-->   n.net.mem
n.assign.dout   --reads-->   n.net.rd_ptr     # array index identifier

# Sequential block
n.always.seq    --sensitive_to-->  n.port.clk   (edge: posedge)
n.always.seq    --sensitive_to-->  n.port.rst_n (edge: negedge)
n.always.seq    --drives-->  n.net.wr_ptr, n.net.rd_ptr, n.net.count, n.net.mem
n.always.seq    --reads-->   n.port.rst_n, n.port.push, n.port.pop, n.port.din,
                             n.net.wr_ptr, n.net.rd_ptr, n.net.count, n.net.full, n.net.empty
n.always.seq    --contains-->  n.case.cnt
```

### Payload (JSON blob hanging off the owning node — opaque to queries)

```json
// payload on n.assign.full
{
  "expr_shape": {"op": "==", "lhs": "count", "rhs": "DEPTH"},
  "lhs_bit_select": null,
  "source": {"file": "fifo.sv", "line": 19, "col": 5}
}

// payload on n.assign.dout
{
  "expr_shape": {"op": "index", "base": "mem",
                 "index": {"op": "slice", "base": "rd_ptr",
                           "msb": "$clog2(DEPTH)-1", "lsb": 0}},
  "source": {"file": "fifo.sv", "line": 21, "col": 5}
}

// payload on n.always.seq
{
  "trigger_kind": "ff",
  "reset_polarity": "active_low_async",
  "body_ast": { /* full statement tree, if/else/case nesting */ },
  "source": {"file": "fifo.sv", "line": 23, "col": 5}
}

// payload on n.net.mem
{
  "packed_width": "WIDTH",
  "unpacked_dims": ["DEPTH"],
  "is_array": true,
  "source": {"file": "fifo.sv", "line": 15, "col": 5}
}

// payload on n.param.depth
{
  "default_value": 8,
  "type": "int"
}
```

---

## Why this split

### "Who drives `dout`?" — one hop
```
neighbors_in(n.port.dout, edge_type='drives')  →  [n.assign.dout]
neighbors_in(n.assign.dout, edge_type='reads') →  [n.net.mem, n.net.rd_ptr]
```
No grep. No name guessing. Pyslang already disambiguated `rd_ptr` from any other `rd_ptr` in another scope.

### "What signals can affect `full`?" — cone of influence (typed BFS)
```
BFS backward via 'drives'+'reads':
  n.port.full
    ← n.assign.full
        ← n.net.count
            ← n.always.seq
                ← n.port.push, n.port.pop, n.port.rst_n, n.port.clk,
                  n.net.wr_ptr, n.net.rd_ptr, n.net.full, n.net.empty
```
Reverse graph falls out for free — `incoming_edges('reads')` is the reverse of `outgoing_edges('drives')`.

### "Is mem[wr_ptr] indexed safely?" — must open the blob
The bit-select range `wr_ptr[$clog2(DEPTH)-1:0]` is in `n.always.seq.payload.body_ast`. Graph navigation gets the agent **to the right always block**; then it reads the payload to see the slice expression. This is the right division of labor: graph for navigation, blob for the detail at the leaf.

### What grep would miss (and the graph catches)
- `dout = mem[rd_ptr[$clog2(DEPTH)-1:0]]` — the identifier `rd_ptr` is *inside* a bit-select inside an array index. The token walk (iter-013 fix) lifts it to a `reads` edge. A regex looking for "identifiers on the RHS" misses this; the LLM grepping for `rd_ptr` finds the line but doesn't know it's an index operand vs a direct read.
- Scope: if another module also has a `count`, grep returns both. The graph holds `n.net.count` *inside* `n.mod.fifo` — no collision.

---

## The rule, restated

| Data                                          | Where it lives        | Reason                                           |
|-----------------------------------------------|-----------------------|--------------------------------------------------|
| Module / port / net / param / assign / always | node                  | These are addresses you traverse to              |
| Direction (drives / reads / sensitive_to)     | edge                  | These are the relationships you filter on        |
| Bit-select ranges, literals, operator trees   | payload on owner node | You only read these *after* arriving             |
| Source file + line + col                      | payload               | Read-once for citations, never traversed         |
| Comment text / docstring prose                | payload               | Pyslang doesn't model it; LLM reads if needed    |

Navigate via graph. Read payload at destination.
