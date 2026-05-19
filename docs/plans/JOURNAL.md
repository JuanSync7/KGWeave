# KGWeave Journal — Lessons Learnt & Next Moves

Append-only log. One entry per coherent move (phase, PR, or focused session).
At the end of each move, the active agent **must** add an entry below with
three sections: **What we did**, **Lessons learnt**, **Next moves**.

Entry skeleton:

```
## YYYY-MM-DD — <move title>
**Branch / commit:** <branch> @ <short-sha>

### What we did
- Bullet, terse, outcome-focused (not narrative).

### Lessons learnt
- One bullet per non-obvious insight worth carrying forward.
  Format: **Lesson** — *why it matters / when it kicks in*.

### Next moves
- Ordered, leverage-first. Each item: action, why now, rough size (S/M/L).
- Mark deferred items with `~~strike~~` and a one-line reason.
```

---

## 2026-05-20 — Kuzu port v1 complete (Phases A–F)
**Branch / commit:** `kgweave/kuzu-port` @ `7f66f74` (18 commits, unpushed)

### What we did
- Ported the research SV-AST extractor into `src/knowledge_graph/` backed by
  Kuzu 0.11.3 with a two-layer schema (structural backbone + semantic promote
  rules), incremental merge keyed on `(uri, source, corpus)`, Pydantic intents
  + read-only-enforced RawCypher, and a thin `__init__.py` facade.
- 8 invariants (I1–I8) each guarded by named tests; 252 new tests, all green.
- Full SV fixture corpus: 7222 nodes / 7721 edges / 6 unresolved placeholders;
  100% edge coverage after Phase C.5 closed the 184-edge type gap.
- Quickstart end-to-end script runs against the public API.

### Lessons learnt
- **Surface gaps the moment you spot them, don't defer them past the phase
  boundary.** — Phase C completion reported `edges_skipped_unknown_type=184`
  (2.4%). Spinning up Phase C.5 *immediately* to close it was cheaper than
  carrying a known-incomplete invariant into D/E. If a "minor" gap touches a
  named invariant (here: I2 completeness), it isn't minor.
- **Pin third-party DB versions hard, and isolate quirks at the boundary.** —
  Kuzu 0.11.3 prepared-statement path needed an `import importlib.util` at the
  top of `store/kuzu.py`. Documenting the workaround inline at the import site
  (not in a separate notes file) means the next upgrade attempt sees it.
- **Generalize the *core*, confine the *language-isms*.** — `source/corpus/lang`
  fields live on the generic Origin/Node tables; SV-only logic (token spans,
  `_unresolved.<name>` synthesis, MERGE-key overrides for `imports_item`) stays
  in `builders/sv/`. Followups for builder #2 won't need a schema change.
- **Replacement-merge needs a key tuple, not just an id.** — Phase A's
  `Origin.id = sha256(uri||sha)` looked sufficient but Phase E needed a
  `(uri, source, corpus)` filter to express "delete the previous version of
  *this* file from *this* builder." Lesson: when designing identity, design
  the *delete-by* predicate at the same time.
- **Parallel subagents can race on the same file.** — Phase C.5 and Phase E
  both touched `builders/sv/writer.py`. The fix was wholesale `Write` + commit
  in C.5 before E started its edit. Better next time: shard by file ownership
  in the dispatch prompt, not by phase.
- **Sentinel offsets break invariant tests silently.** — pyslang's
  `0xFFFFFFFFF` SyntaxList end offset passed all type checks but produced
  zero-length anchors that failed I3 round-trip. `_backfill_empty_spans`
  post-pass caught it. Lesson: round-trip tests catch what type checks can't.

### Next moves
1. **Per-file syntax-tree cache in `builders/sv/lift.py`** — keyed on
   `(uri, sha256)`. Cuts touched-file extract from ~8s to <1s. *Why now:*
   only gap with real user-felt cost. *Size:* M.
2. **`:Meta` node + `schema_version` assert on `open_store`** — forward-compat
   insurance before anyone opens an old store. *Size:* S.
3. **Re-point `research/ast_experiment/demo/` at the Kuzu store via the
   facade** — exercises the public API in anger and removes the duplicate
   in-memory codepath. *Size:* M.
4. **Push `kgweave/kuzu-port` and open PR** — externalize for review. *Size:* S.
5. **Origin GC sweep (`prune_orphaned_origins`)** — replacement merge leaves
   Origin rows when their last node is deleted. *Size:* S.
6. **Builder #2 scaffold (Python via libcst *or* markdown via mistune)** —
   minimum needed: register a builder, write one node table, then wire a real
   cross-builder connector. *Why now:* unlocks the multi-builder story the
   schema was designed for. *Size:* L.
- ~~Real cross-builder connector~~ — defer until builder #2 exists; otherwise
  there's nothing to connect SV nodes *to*.
- ~~Query result streaming, Cypher autocomplete, blob compression~~ — none
  block real use at current corpus size.
