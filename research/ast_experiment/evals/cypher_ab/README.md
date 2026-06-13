# `cypher_ab` — Cypher vs pattern-dict accuracy A/B

Does an LLM traverse the SV knowledge graph **more accurately** with Cypher or
with the pattern-dict `graph_query` surface? Settled by blind measurement.

**Result:** Cypher **5/6** across opus/sonnet/haiku vs pattern-dict **3/2/2**.
Full write-up + caveats: [`CYPHER_VS_DICT_RESULTS.md`](CYPHER_VS_DICT_RESULTS.md).

## Files

| file | role |
|---|---|
| `kuzu_load.py` | load the lifted graph dict into an embedded **kuzu** DB (one `N` node table; one rel table per semantic edge type) so real Cypher runs on the same graph |
| `questions.py` | 6 questions spanning the differentiating axis + independent truth + both-surface oracles; `accept_fns` neutralise the name/path projection lever |
| `card_cypher.md` | the Cypher schema card the blind panel sees (parallel to `docs/SCHEMA_CARD.md`, the dict card) |
| `run_ab.py` | validate both surface ceilings; grade blind `--replay` files by executing each surface |
| `blind_runs/` | the panel's answers (`{cypher,dict}_{opus,sonnet,haiku}.json`) |

## Run

```bash
uv pip install kuzu            # eval-only dependency
# surface ceilings (no model):
uv run python -m research.ast_experiment.evals.cypher_ab.run_ab
# grade a blind file:
uv run python -m research.ast_experiment.evals.cypher_ab.run_ab \
    --surface cypher --replay blind_runs/cypher_opus.json
```

Not wired into the pytest suite (needs the optional `kuzu` dep + is a one-off
measurement, not a regression gate).
