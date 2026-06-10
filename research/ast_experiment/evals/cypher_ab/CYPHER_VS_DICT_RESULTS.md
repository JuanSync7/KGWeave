# Cypher vs pattern-dict — accuracy A/B

**Question (driver: LLM accuracy).** Should the graph expose **Cypher** or the
current **pattern-dict** `graph_query` surface? Settled the same way as the
consolidation question — by blind measurement, not debate.

**Method.** Six questions chosen to span the *differentiating* axis (easy lookups
where both surfaces tie tell us nothing): two controls + four where the surfaces
diverge. A blind panel of three models (opus/sonnet/haiku) answered all six from
**only** a schema card — `/tmp/card_dict.md` (the real `SCHEMA_CARD.md`) or
`/tmp/card_cypher.md` — no repo/graph access. Answers are **executed** against the
*same* graph: pattern-dict via `graph_query`/named tools; Cypher via an embedded
**kuzu** DB loaded from the same node/edge set (`kuzu_load.py`). The name-vs-path
projection convention (a separate, already-known lever) is **neutralised** —
either projection of the right node set passes — so this measures *surface
capability*, not projection style. Truth is computed independently (`questions.py`).

Requires `uv pip install kuzu`. Reproduce:
`uv run python -m research.ast_experiment.evals.cypher_ab.run_ab --surface {cypher|dict} --replay blind_runs/<file>.json`

## Result

```
surface/model   Q1  Q2  Q3  Q4  Q5  Q6
 cypher/opus     ✓   ✓   ✗   ✓   ✓   ✓   = 5/6
 cypher/sonnet   ✓   ✓   ✗   ✓   ✓   ✓   = 5/6
 cypher/haiku    ✓   ✓   ✗   ✓   ✓   ✓   = 5/6
   dict/opus     ✓   ✗   ✓   ✗   ✗   ✓   = 3/6
   dict/sonnet   ✓   ✗   ✓   ✗   ✗   ✗   = 2/6
   dict/haiku    ✓   ✗   ✓   ✗   ✗   ✗   = 2/6
```
Surface ceilings (oracles): **cypher 5/6, dict 3/6.**

| Q | axis | who can express it |
|---|---|---|
| Q1 | containment (control) | both ✓ |
| Q2 | OR across two edges (`port` **or** `net`) | **Cypher only** (`-[:has_port\|has_net]->`); dict has no edge-union, no tool |
| Q3 | transitive fan-in cone | **dict only** — its bespoke `cone_of_influence` tool; the alternating `signal<-drives-assign-reads->signal` walk has no clean Cypher form |
| Q4 | multi-column return `(inst, module)` | **Cypher only** (`RETURN i.path, m.name`); dict projects one column |
| Q5 | aggregation (count) | **Cypher only** (`count()`); dict has no aggregation |
| Q6 | 2-hop dataflow (control) | both express; weaker dict models mis-selected |

## Findings

1. **Cypher's higher ceiling converts to real accuracy — uniformly across tiers.**
   On the three questions needing OR / multi-column / aggregation, **all three
   models including Haiku** wrote correct, idiomatic Cypher first try. The dict
   surface *structurally cannot* express these (ceiling 3/6), so no model could,
   regardless of capability.

2. **Cypher's feared downside did not bite.** Across the 17 Cypher queries the
   panel generated, **zero syntax/execution errors** — the "error surface" cost
   (vs the dict's can't-malform guarantee) never materialised. Cypher is the
   query language these models have seen most; they write it cleanly.

3. **The pattern-dict surface degrades with model strength — a second failure
   mode.** Opus hit the dict ceiling (3/6) by correctly recognising the 3 gaps.
   But Sonnet/Haiku *also* fumbled an *expressible* question (Q6): Sonnet picked
   the wrong wrapper (`find_drivers` returns the drivers, not the signals they
   read), Haiku modelled "port **or** net" as *chained* follows (port→net-of-port
   → silently empty) and did `drives`-in without the `reads`-out hop. So
   "restricted DSL + a menu of named tools" adds a *tool-selection / pattern-
   modelling* burden on top of the expressivity cap, and that burden hits weaker
   models hardest.

4. **The dict's one genuine win is curated domain walks.** `cone_of_influence`
   answered the transitive question (Q3) that no model could express in plain
   Cypher. Domain-specific traversals (alternating fan-in cones, etc.) are more
   reliably delivered as a named/curated query than reconstructed ad-hoc — but
   that advantage is **not exclusive to the dict surface**: the same walk can be
   a saved/parameterised Cypher query or a UDF exposed *alongside* Cypher.

## Verdict (for the accuracy driver)

**On this corpus, Cypher wins on accuracy — 5/6 across every model tier vs the
pattern-dict's 3/2/2.** It expresses the query shapes the dict structurally can't
(OR, multi-column, aggregation), models write it correctly with no error-surface
penalty, and — unlike the dict's named-tool model — it doesn't degrade as model
capability drops. The dict's sole edge (curated transitive tools) can be kept by
exposing those few walks as saved queries alongside Cypher.

This **flips the prior recommendation** ("extend the pattern-dict at its gaps").
The earlier blind data only covered easy lookups where both surfaces tie; once
the questions get non-trivial, the expressivity gap is decisive. Measuring earned
the reversal.

## Caveats (don't over-read)

- **Small N**: 6 questions, 1 corpus, 3 models, single run. Directional, not
  definitive.
- **Deliberately weighted** to the differentiating axis. On pure easy lookups
  both surfaces tie (Q1), and the existing 22-case eval shows the dict surface is
  ~96–100% there. This says "*when queries get non-trivial*, Cypher pulls ahead,"
  not "Cypher is better on the average query."
- **Cost not modelled**: Cypher needs a real engine (kuzu/Neo4j) — a dependency,
  an operational surface, and the loss of the dict's "can't-malform" guarantee
  (empirically unused here, but real at scale).
- **Cone-in-Cypher** is a real, narrow Cypher weakness; mitigated by a saved query
  or by keeping the named tool.
- **Projection neutralised** here on purpose; it remains a separate lever worth a
  canonical convention in whichever surface is chosen.
