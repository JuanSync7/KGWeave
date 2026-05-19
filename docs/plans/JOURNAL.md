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

## 2026-05-20 — v1.2 slate (#1–#6) — Kuzu port follow-ups
**Branch / commit:** `kgweave/kuzu-port` @ `d895214` (7 commits on top of v1, pushed; PR #1 open)

### What we did
- **#1 Per-file lift cache** (`54a4321`, `954e7ff`) — keyed on `(uri, sha256, id_prefix)`,
  warm-lift <50ms; corpus-global `promote()` now the dominant cost.
- **#2 `:Meta.schema_version` assert** (`558504a`) — typed `SchemaVersionMismatch`
  on open; legacy stores auto-migrate up. Constant bumped 1.2.0 → later 1.3.0 in #6.
- **#3 Demo re-pointed at Kuzu via facade** (`68f14a5`) — new
  `export_demo_graph_kuzu.py`; 13/13 structural-diff tests vs legacy exporter.
  Caught and patched an I2 regression where `_unresolved.*` edges were stripped
  pre-write in `_filter_graph_to_origins`.
- **#4 PR opened** — https://github.com/JuanSync7/KGWeave/pull/1 (24+ commits, base `main`).
- **#5 Origin GC sweep** (`b76f7ed`) — `prune_orphaned_origins(*, source, corpus) → int`
  + `extract(gc=True)` closes the "removed-file" case while preserving I7 isolation.
- **#6 Markdown builder + SV↔MD connector** (`d895214`) — `builders/md/` with
  MdDocument/Heading/CodeFence/InlineCode; `SvMarkdownReferenceConnector` writes
  REFERENCES edges to SV `ModuleDeclarationSyntax`. Schema bumped 1.3.0.
- Final regression: 1083 passed / 0 fail (after fixing the literal version pin from #2).

### Lessons learnt
- **Subagent reports can outpace their commits.** — #2 and #6 both left
  uncommitted diffs in the worktree; main agent had to inspect, run regressions,
  and commit on their behalf. **Why:** subagents sometimes interpret "test
  green" as "done" without staging. **How to apply:** always end the subagent
  prompt with "your move is only complete when `git log` shows your commits,"
  AND verify with `git status` in the main agent before marking the task done.
- **Schema version bumps interact across sequential subagents.** — #6 bumped
  to 1.3.0 but #2 had pinned `== "1.2.0"` in a test. Each version-bumping
  subagent should be told to *generalize* version assertions (regex/format
  check), not pin literals. **Why:** sequential dispatch hides cross-move
  coupling; the second subagent breaks the first's test silently. **How to
  apply:** when a move includes a version bump, the test for it must check
  *shape* (`re.match(r"\d+\.\d+\.\d+", v)`) not *literal*.
- **The pre-write filter (`_filter_graph_to_origins`) is a recurring
  losslessness footgun.** — Phase C.5 missed `_unresolved.*` because the
  writer's placeholder loop runs *after* the dst-must-be-in-keep filter. v1.2-#3
  rediscovered it. **Why:** any new synthetic-id pattern in any builder will
  trip this filter the same way. **How to apply:** when introducing synthetic
  ids (`_unbound.*`, `_external.*`, …), check `_endpoint_ok` covers them
  before writing tests.
- **TDD-then-Ralph caught real bugs, not just polish.** — #3's diff test
  surfaced the I2 regression; #5's filter-scope test caught a near-I7 break.
  **Why:** assertions framed against an *external* reference (legacy exporter,
  sibling builder) are stronger than assertions internal to the new code.
  **How to apply:** for any move that re-implements existing behavior, the
  first test should diff against the prior implementation.
- **Per-file caching only helps if downstream stages are also per-file.** —
  #1 reduced lift to <1s but touched-extract is still 28s because `promote()`
  is corpus-global. **Why:** caching at the wrong layer compounds the layers
  below it. **How to apply:** before caching, profile to confirm the cached
  stage is the dominant cost; otherwise document the next bottleneck.
- **Kuzu 0.11.x has a real `NOT EXISTS` subquery gap.** — #5 needed a
  two-pass collect-then-filter for orphan detection. **Why:** correlated
  `NOT EXISTS` in `WHERE` is unreliable on this version. **How to apply:**
  document as a portability note for the next Kuzu upgrade; revisit the
  one-shot Cypher when bumping.
- **REFERENCES edge type was already declared in #2's Phase-C.5 leftovers** —
  reusable for cross-builder linking. **Why:** generic edge types pay off
  exactly when a second builder lands. **How to apply:** when adding edges
  for builder N, ask whether builder N+1 needs the same primitive before
  giving it an SV-specific name.

### Next moves
1. **Cache `promote()` semantic-rule outputs per-file under a corpus-hash
   fingerprint** — the new bottleneck after v1.2-#1. *Why now:* unblocks
   <1s touched-extract for editor/LSP usage. *Size:* M.
2. **Replace the `:Meta` literal check with a strict `>=` semver compare** —
   today equality-only blocks even patch-level forward-compat. Add a `compat`
   policy so 1.3.1 can open a 1.3.0 store. *Size:* S.
3. **Promote the bucket-1 categorisation parser and `RULE_FAMILIES` table to
   a shared module** (`research/ast_experiment/scripts/_demo_common.py`)
   shared by both exporters. *Why now:* both copies will drift. *Size:* S.
4. **Add `stats.gc_pruned` to `ExtractStats`** so callers can see what
   `gc=True` removed. *Size:* S.
5. **Generalise the connector beyond SV-module names** — module ports,
   typedefs, package names. *Why now:* the architecture supports it; today's
   matcher only sees modules. *Size:* M.
6. **Pre-existing broken `tests/knowledge_graph/builders/sv/legacy_tests/demo/`**
   — references a `tests/knowledge_graph/research/...` path that doesn't exist.
   Either delete or fix the path. *Size:* S.
7. **Gitignore `tests/knowledge_graph/builders/sv/covered_classes.json`** —
   generated test artifact, currently untracked noise. *Size:* XS.
- ~~Persistent on-disk lift cache~~ — defer until editor/LSP integration
  forces it.
- ~~Docstring builder, link resolution, fuzzy module-name matching~~ —
  generalisation work that belongs after #5 above.

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
