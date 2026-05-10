# KGWeave Eval Harness

Entity-recall benchmark for KGWeave against a public RISC-V SoC corpus.

## Layout

- `qa_ibex.yaml` — 50 golden Q&A pairs targeting [lowRISC Ibex](https://github.com/lowRISC/ibex). **Status: DRAFT — needs human review.** Entity names follow the KGWeave convention `<module>.<port|signal|param>`.
- `../src/kgweave/evals/` — harness code (`schemas`, `metrics`, `loader`, `runner`).
- `../tests/evals/` — TDD coverage (28 tests, including a sanity gate against `qa_ibex.yaml`).

## Question categories (50 total)

| Category | Count | What it probes |
|---|---|---|
| `structure` | 15 | `contains` edges (ports, signals, parameters per module) |
| `hierarchy` | 10 | `instantiates`, `instance_of`, `part_of` |
| `connectivity` | 10 | `connects_to` across module boundaries |
| `parameters` | 10 | parameter resolution + semantics |
| `architecture` | 5  | high-level pipeline / ISA questions |

## Running an eval

```python
from kgweave.evals import load_qa_set, run_eval
from kgweave.knowledge_graph import get_graph_backend, get_query_expander

qas = load_qa_set("evals/qa_ibex.yaml")
backend = get_graph_backend()
expander = get_query_expander(backend=backend)

def predictor(qa):
    # Stub: replace with whatever pipeline you want to evaluate.
    return expander.expand(qa.question).entities

results, agg = run_eval(qas, predictor)
print(f"F1={agg.mean_entity_f1:.3f} R={agg.mean_entity_recall:.3f} N={agg.num_questions}")
```

The harness is decoupled from any specific retrieval pipeline — the predictor is a `Callable[[QAPair], Iterable[str]]` so KG expansion, plain vector search, and a hybrid can each be benchmarked against the same gold set.

## Review checklist for `qa_ibex.yaml`

Before this set can be considered authoritative, walk each question against an actual Ibex checkout (commit pinned in CI):

1. Module names exist (`ibex_core`, `ibex_id_stage`, etc.) — Ibex occasionally renames modules between branches.
2. Port names match the SV (`clk_i` vs `clk`, `rst_ni` vs `rst_n`).
3. Hierarchy answers reflect what the parser_extractor + slang analyzer actually emit (definition-level vs hierarchical-path entity names).
4. Connectivity answers point at real netlist nodes after pyslang elaboration.
5. Parameter answers reflect Ibex's current `localparam` / `parameter` set, including any post-OpenTitan integration changes.

Drop or rewrite any Q where the gold entities don't match the source.

## Why Ibex

- Pure SystemVerilog → exercises the new pyslang elaboration path end-to-end.
- Apache 2.0 license → reproducible in CI without auth.
- Manageable size (~30 SV files for the core, ~80 with the OpenTitan integration shell) — fast enough to run on every PR.
- Real chip-design vocabulary: pipeline stages, CSRs, PMP, debug, interrupts.
