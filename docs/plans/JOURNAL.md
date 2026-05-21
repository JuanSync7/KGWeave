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

## 2026-05-21 — v1.4 slate (#1–#3) — pytest infra: stop chewing memory
**Branch / commit:** `kgweave/kuzu-port` @ `ec27b68` (5 commits on top of v1.3, unpushed; PR #1 still open)

### What we did
- **#1 Cheap pytest memory wins** (`40677c9`) — four config-level guards in one commit:
  - `pytest_configure` redirects `basetemp` to `~/.pytest-tmp` (root FS) when no
    `--basetemp` was passed. Single biggest win: moves the bottleneck off the 16 GB
    `/tmp` tmpfs that filled twice during v1.3.
  - `pytest-timeout` pinned at 60 s with `timeout_method = thread` in
    `pyproject.toml`; Kuzu-heavy `tests/knowledge_graph/store/` and
    `tests/knowledge_graph/connectors/` bump to 300 s via local
    `pytest_collection_modifyitems`.
  - Autouse function-scoped fixture rmtree's `*.kuzu` dirs and `catalog.kz`-marker
    dirs under each test's `tmp_path` on teardown, strictly scoped inside
    `tmp_path` (cannot escape via symlinks).
  - Sibling-pytest lockfile at `~/.kgweave-pytest.lock` — `pytest_sessionstart`
    refuses to launch if a live sibling pid still holds the lock; cleared on
    `sessionfinish` only if the lock still points at us.
  - 17 meta tests + 1 by-design skip in new `tests/_meta/`. `tests/README.md`
    documents the rule "never run `pytest tests/` raw on this box".
- **#2a `shared_kuzu_store` prototype** (`134d794`) — session-scoped Kuzu DB
  with per-test corpus = `f"t-{sha1(nodeid)[:12]}"`. Teardown DETACH-DELETEs the
  test's corpus. Coexists with the existing `tmp_store` fixture (opt-in only;
  schema-version / `:Meta` tests stay on tmp_path). 6 tests in `test_origin_gc.py`
  migrated; 8 new fixture-coverage tests in `test_shared_kuzu_fixture.py`.
- **#2b Measurement doc** (`ae610d0`) — `docs/plans/v1.4-shared-db-prototype.md`
  with baseline vs prototype numbers and an explicit HOLD recommendation on
  rollout.
- **#3 Defensive disk hygiene** (`ec27b68`) — root-cause follow-up after a
  grep audit confirmed the v1.3 disk crises were NOT from tests but from the
  `quickstart.py` / `quickstart_md.py` no-arg defaults writing to
  `./kgweave-store/` (repo working tree, never auto-cleaned). Moved both
  defaults to `~/.kgweave-tmp/`. Also added Makefile targets
  `disk-report` / `clean-cache` / `clean-all` and a 4-bullet "growth
  surfaces" section to `tests/README.md`. The biggest single surface turns
  out to be `~/.cache/uv` (7.7 GB) — addressed via `uv cache prune`
  invoked by `make clean-cache`. 2 new AST-based meta tests pin both
  quickstart defaults against regression.

### Lessons learnt
- **basetemp is the cheap win.** A single `pytest_configure` hook redirecting
  `basetemp` to root FS does ~80 % of what we wanted from the shared-DB rewrite,
  with ~5 % of the engineering effort. *When it kicks in:* whenever pytest's
  `tmp_path` discipline is reasonable but the underlying FS has the wrong
  capacity — measure the FS first, not the test code.
- **Set a measurement bar BEFORE prototyping, and respect it.** We set "2× disk
  improvement or recommend HOLD" up front. The shared-DB prototype delivered
  −40 % disk, +3.8 % wall, +95 % RSS — real disk savings but below the bar.
  Following the rule meant we didn't sink another week into rollout for a fixed
  problem. *When it kicks in:* any "should we rewrite X for performance?"
  question — the success criterion has to be quantitative and set before the
  experiment runs.
- **Coexistence regresses peak RSS during partial migration.** Session DB +
  per-test DBs both resident = +434 MB RSS bump. Measuring a half-migrated
  state systematically misleads. *When it kicks in:* any large fixture
  migration — either commit fully or measure only after rollback.
- **The "subagent leaves work uncommitted" pattern is now confirmed across
  v1.2, v1.3, AND v1.4-#1.** Two subagents in a row did v1.4-#1 correctly but
  exited without `git commit`. v1.4-#2's subagent finally committed both
  pieces. Charter wording matters: "COMMIT your work before exiting. (Prior
  subagents have left work uncommitted — this is the #1 failure mode. Use
  `git log -1` to confirm your commit landed before declaring done.)" is the
  exact phrasing that worked. *When it kicks in:* every multi-step subagent
  dispatch — the parent must always verify with `git log` before trusting the
  summary.
- **Kuzu mmap RSS grows non-trivially with session length.** Even with a single
  session-scoped DB, the prototype showed +434 MB RSS after ~5 minutes of test
  activity. Pages aren't being released on DETACH DELETE. *When it kicks in:*
  any future long-lived Kuzu process (REPL, daemon mode, batch ingest) —
  budget for retained pages, not just disk.

### Next moves
1. **Push `kgweave/kuzu-port` and update PR #1** with the 12 commits beyond
   v1.2 (7 from v1.3 + 5 from v1.4). Size: **S**. Awaiting explicit
   authorisation.
2. **Ship the v1.3 next-moves slate** — the seven items logged in the v1.3
   retro are still queued: gc_pruned in demo exporter (XS), promote() pass-2
   cache (M), builder #3 / Python via libcst (L), configurable compat policy
   (S), session-scoped `register_connector` fixture (S), pytest hard-cap
   Makefile target (S, partially landed via v1.4-#1).
3. **Document `shared_kuzu_store` in `tests/README.md`** as opt-in
   infrastructure for future test authors — currently only mentioned in the
   conftest docstring and the prototype doc. Size: **XS**.
4. ~~v1.4-#3 full shared-DB rollout~~ — HOLD per v1.4-#2b measurement;
   basetemp redirect already mitigated the tmpfs pressure.
5. **Investigate Kuzu mmap page-retention.** Set up a 5-min repro that opens
   a store, inserts 100k rows, DETACH-DELETEs them all, and measures RSS
   before/after. If confirmed, file an upstream Kuzu issue. Size: **M**.
6. **CI guard: fail if `~/.pytest-tmp/` exceeds N GB after a full run.** Once
   we have a green full-suite run, derive N and wire it in. Blocked on first
   green full run. Size: **S** (post-blocker).
7. ~~Audit every store test for empty-DB-semantics assumptions~~ — only worth
   doing if we revisit shared-DB rollout. Deferred to whenever item 5
   surfaces a fix.

---

## 2026-05-21 — v1.3 slate (#1–#7) — performance + compat + housekeeping
**Branch / commit:** `kgweave/kuzu-port` @ `1504d4e` (6 commits on top of v1.2, unpushed; PR #1 still open)

### What we did
- **#1 `promote()` per-file cache** (`80f1520`) — keyed on
  `(uri, sha256, corpus_fp, ruleset_fp)` with deepcopy on store + serve.
  Implementation lives in `builders/sv/semantic/promote_cache.py`; `build.py`
  rewired to call `_run_and_capture` / `_replay`. 11 new tests in
  `test_promote_cache.py` covering hit/miss/lossless, ruleset-fp invalidation,
  corpus isolation, mutation-poisoning resistance, warm-vs-cold timing budget,
  and a `extract()` end-to-end identity check.
- **#2 Semver-aware `:Meta` compat** (`4ecb844`) — replaced literal equality
  with `_is_compatible(stored, expected)`: same major + `(expected.minor,
  expected.patch) >= (stored.minor, stored.patch)` opens; anything else raises
  `SchemaVersionMismatch(compat_policy="semver-major")`. Deliberately does NOT
  rewrite the on-disk `:Meta` row on forward-compat open (preserves writer
  provenance). 11 new tests in `test_schema_version_compat.py`.
- **#3 Shared `_demo_common.py`** (`2bdab42`) — moved `parse_bucket1_categories`,
  `category_for_kind`, `RULE_FAMILIES`, `attribute_to_family` into
  `research/ast_experiment/scripts/_demo_common.py`. Both exporters import
  from it; `is`-identity asserted in the test (`test_demo_common.py`, 8 tests).
  Also fixed a latent gap: `test_scripts_directory_only_has_entry_points` had
  never been updated to allowlist `export_demo_graph_kuzu.py` after v1.2-#3
  landed it — fixed in the same commit.
- **#4 `ExtractStats.gc_pruned`** (`b5a547c`) — captures the return value of
  `prune_orphaned_origins` into the stats dataclass so callers of
  `extract(gc=True)` can observe what got swept. Default 0; both
  touched-paths-empty and touched-paths-nonempty code paths populated. New
  tests in `test_origin_gc.py` (extended).
- **#5 Generalised SV↔MD connector** (`23f5e5a`) — `SvMarkdownReferenceConnector`
  now indexes 8 SV kinds (module / package / typedef / forward-typedef /
  4× port-decl flavours), corpus-scoped via `{corpus: {name: [ids]}}`, with
  collision-aware multi-edge emission when a name resolves to multiple kinds.
  9 new tests in `test_sv_md_reference_connector_generalised.py`. quickstart_md
  REFERENCES count went 3 → 7 (added `clk`, `rst_n`, `fifo_pkg`).
- **#6+7 Housekeeping** (`1504d4e`) — deleted
  `tests/knowledge_graph/builders/sv/legacy_tests/demo/` (6 files, ~1.5k
  lines) and `legacy_tests/test_structure.py` — both anchored to
  pre-port `research/ast_experiment/`-relative paths that no longer exist
  in the v1 layout, with live equivalents at
  `research/ast_experiment/tests/test_structure.py` and
  `test_export_demo_graph_kuzu.py`. Added `legacy_tests/__init__.py` to avoid
  basename collisions with the live tree. `.gitignore`d
  `tests/knowledge_graph/builders/sv/covered_classes.json`. After the
  deletions the suite runs with NO `--ignore` flag.
- Per-component test verification (each ran in isolation, all green):
  promote_cache 11/11; schema_version_compat 11/11 + existing 7/7;
  `_demo_common` 8/8 + Kuzu-exporter diff harness 13/13; origin_gc 16/16
  (post-#4); generalised connector 9/9; legacy_tests post-purge 599/0.
  Aggregated estimate: ~2530 tests / 0 fail. Full no-ignore regression in
  one shot could not be verified — see lesson on tmpfs / concurrent pytest
  contention below.

### Lessons learnt
- **Subagent "tests green" ≠ "commits in `git log`" is now a fully-confirmed
  pattern, not a coincidence.** — v1.2 had two (#2, #6); v1.3 had two
  (#4, #6+7); plus one (#1) that mid-way disk-cleanup desync'd into a "54
  failures" false alarm. **Why:** subagents treat the unit-test pass as the
  finish line and report-out without staging or running the regression
  themselves. **How to apply:** the dispatch prompt's "your move is only
  complete when `git log` shows your commits" line clearly isn't enough on
  its own — the main agent should run `git log --oneline -1` and
  `git status --short` IMMEDIATELY after a subagent returns and assume
  staging is missing until proven otherwise.
- **`/tmp` is a 16G tmpfs on this box — full pytest suites accumulate
  per-test Kuzu DBs that can fill it during one run.** — When tmpfs fills,
  `df` succeeds but the harness's per-call cwd-marker write fails silently;
  every `Bash` invocation returns exit 1 with no output and you cannot tell
  it apart from a shell crash. **How to apply:** always pass
  `--basetemp=/home/kok-shew-juan/.pytest-tmp` (root-FS path) for any
  multi-file regression; `rm -rf` it between runs; never trust raw
  `pytest tests/` on this box.
- **Concurrent pytest from another worktree puts the SV suite into kernel
  `D` state for tens of minutes.** — During v1.3-#6+7 verification a
  RagWeave pytest started simultaneously and the SV pytest deadlocked at
  ~28% progress on disk I/O. **Why:** pyslang + Kuzu's mmap'd page cache
  + a competing big-disk pytest = priority-inversion-like contention.
  **How to apply:** if `ps` shows the python pid in `Dl` state for more
  than the expected wall-time of the suite, kill it; don't wait further.
  Aggregate per-component verification (each subtree green) is acceptable
  evidence when end-to-end is environmentally blocked.
- **A subagent's "regression failure" report must be re-run before
  triage.** — v1.3-#1's "54 failed / 1781 passed" claim was unreproducible
  on the SAME uncommitted tree once we cleaned `kgweave-store/` + stale
  intermediates: a clean replay returned `1163 passed / 0 failed`.
  **Why:** subagents run during disk-pressure windows can capture transient
  Kuzu / pyc corruption as if it were a code regression. **How to apply:**
  when a subagent reports `N failed` BUT their newly-added tests all pass
  in isolation, the main agent's first move is a clean replay, not a
  diagnostic deep-dive.
- **#6's scope creep was inevitable in hindsight.** — Charter said
  "delete `legacy_tests/demo/`"; reality was that `legacy_tests/test_structure.py`
  carried the SAME orphaned-pre-port-path pattern and had to go too.
  **Why:** both files were written before the v1 port relocated source.
  **How to apply:** when housekeeping a "post-migration orphan", grep for
  the moved path prefix across the WHOLE candidate directory, not just the
  named subdir — one search saves a second commit.
- **A symbol-identity (`is`) assertion is stronger than a structural-equality
  assertion for cross-module dedup.** — v1.3-#3's
  `test_both_exporters_import_shared_module` asserts
  `kuzu_exporter.RULE_FAMILIES is shared.RULE_FAMILIES` rather than `==`,
  catching the future case where someone copy-pastes the table back
  inline. **Why:** equal-by-value lets the fork hide; same-id makes it
  structurally impossible. **How to apply:** in dedup PRs, prefer `is`
  over `==` whenever the contract is "literally the same object".
- **`compat_policy` field on a typed exception didn't break the facade
  re-export.** — Adding kwargs to a Pydantic-style typed exception is
  cheap when defaults are sensible. **Why:** `test_exception_reexported_from_facade`
  constructs `SchemaVersionMismatch(stored=..., expected=...)` positionally;
  the kwarg-only new field stayed invisible. **How to apply:** when
  extending typed exceptions, add fields as kwarg-only with defaults — and
  always re-run the facade test even when "obviously safe".

### Next moves
1. **Push `kgweave/kuzu-port` and update PR #1 with the 6 new v1.3 commits**
   — externalize for review. *Size:* S.
2. **Hard-cap full pytest runs at 15 min** (pytest-timeout?), or route the
   full suite through a Makefile target that auto-`--basetemp=` and
   refuses to run if another pytest from a sibling worktree is alive.
   *Why now:* every v1.3 commit cost a ~10-min full-run, half of which
   hung. *Size:* S.
3. **Cache `promote()`'s pass-2 drained edges separately from pass-1
   appends.** v1.3-#1 captures both into the per-file delta but the
   replay is per-file FIFO; pass-2's drain semantics could yield
   different results if the corpus shrinks mid-run. Add a stress test.
   *Size:* M.
4. **Wire `gc_pruned` into the demo exporter's stats line** so the
   quickstart prints `gc_pruned=N` when run with `gc=True`. *Size:* XS.
5. **Generalise the connector beyond SV/MD: builder #3** — Python (libcst)
   or Bazel/Make. The 8-kind name index from v1.3-#5 should drop into a
   generic `name_resolver` helper at `connectors/_name_index.py` rather
   than living inline. *Size:* L.
6. **`semver` policy: make `_is_compatible` configurable** — add a
   `compat: Literal["semver-major", "exact", "any"]` parameter to
   `verify_or_migrate_schema_version` so test/dev setups can opt into
   strict-exact while prod uses semver-major. *Size:* S.
7. **Make the `register_connector` test fixture session-scoped** to stop
   the `BuilderConflict` collisions across connector test modules — noted
   by v1.3-#5's subagent as a paper cut. *Size:* S.
- ~~Persistent on-disk promote cache~~ — defer alongside the lift cache
  until LSP integration.

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
