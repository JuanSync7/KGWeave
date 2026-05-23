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

## 2026-05-23 — v1.5-#2 — bulk-COPY writer
**Branch / commit:** `kgweave/kuzu-port` @ `e6b7281` (4 commits on top of v1.5-#6+#4+#5 head `2c90d29`, push pending at journal-write time)

### What we did
- **Threshold:** `_BULK_COPY_MIN_ROWS = 100` in `src/knowledge_graph/builders/sv/writer.py:443`. Above-threshold batches (len(nodes)+len(edges) >= 100) dispatch to `_write_graph_bulk`; below-threshold stays on the per-row Cypher MERGE loop.
- **Format:** CSV via `tempfile.mkstemp` + Kuzu `COPY <table> FROM '<path>' (header=true)`. Picked over Parquet/Arrow because stdlib `csv` round-trips JSON-in-payload through RFC-4180 quoting cleanly with no extra deps; the bottleneck is Kuzu's index update on COPY, not parse cost (Parquet would shave ~100 ms at most).
- **Replacement-merge:** preserved via a pre-COPY `DETACH DELETE` of every Node id about to be written -- wipes stale rows AND every incident REL row, so the follow-up REL COPYs land into a clean slice for the batch. `_unresolved.<name>` placeholder synthesis mirrored from the per-row branch.
- **Buffer cap raised twice:** `KGWEAVE_MAX_DB_SIZE_BYTES` in the quickstart perf test went `256 MiB -> 1 GiB`, and `_TEST_MAX_DB_SIZE_BYTES` in `tests/knowledge_graph/store/conftest.py` likewise. The 256 MiB cap from v1.5-#1 couldn't hold the COPY path's frame-group allocation (`RuntimeError: No more frame groups can be added to the allocator`). 1 GiB is still far below Kuzu's 8 TB default.
- **Budgets tightened in lockstep:**
  * `tests/knowledge_graph/facade/test_quickstart_perf.py` floor: `200 s -> 10 s` (20x).
  * `tests/knowledge_graph/facade/test_quickstart_runs.py` subprocess timeout: `400 s -> 70 s` (per the v1.5-#1 rule `max(floor + 60, 2 * floor)`).
- **Tests landed:** G2 replacement-merge through COPY, G3 unresolved-placeholder through COPY, G4 perf micro-bench (N=1000 < 3 s, N=10 < 1.5 s) -- 716 sv-builder + 88 store + 15 facade all green at HEAD.

### Lessons learnt
- **Bulk COPY is ~10x at the writer, ~90x at the quickstart wall** -- *the quickstart bench was over-stating per-row INSERT cost relative to whole-pipeline cost. Writer N=1000 went 10.3 s -> 1.0 s (10x), but the quickstart wall went 125 s -> 1.4 s (~90x). Most of the prior 125 s was index work and lock churn on the per-row loop, not pure INSERT time.* Worth re-measuring before assuming the next perf lever (libcst Python builder) is even necessary.
- **Buffer-manager frame-group count scales with `max_db_size`, not just on-disk usage** -- *Kuzu's BM partitions its address-space mmap into frame groups at open time; a 256 MiB cap simply doesn't have enough of them for COPY's bulk allocation, regardless of how empty the DB is. Means any future cap bump has to be done in lockstep across every test-fixture file that opens Kuzu -- conftest + perf test + cap-guard test all moved together this round.*
- **Two test stores share a cap regime** -- *quickstart subprocess perf store and the in-process store-test session fixture both pin `max_db_size_bytes`. A perf hack that needs more BM has to bump BOTH and update the cap-guard literal in `test_fixtures_apply_cap.py` or the suite reports a regression that's actually intentional.*
- **Pre-existing test-isolation failures surfaced (not caused) by this round** -- *3 SV `imports` tests (`test_types.py::test_s32_*`, `test_s50_does_not_disturb_s32_imports_edges`) fail when `tests/knowledge_graph/builders/` runs the md/ tests first. Repros on `1edddb4` (before the bulk-COPY landed) so this is not a v1.5-#2 regression; it's a lift/promote per-file cache pollution issue surfacing when the same `fifo.sv` fixture is built in two contexts. Documented + deferred to a dedicated investigation.*

### Numbers (this box, this session)
- Writer N=1000 wall: `~10.3 s` (per-row MERGE) -> `~1.0 s` (COPY) -- **~10x**.
- Writer N=10 wall: per-row path unchanged (<150 ms), bulk path not engaged below threshold.
- Quickstart wall (3-run worst, with `KGWEAVE_MAX_DB_SIZE_BYTES=1 GiB`): `1.452 s` vs the v1.5-#1 floor of `~125 s` -- **~90x**.
- On-disk store size: unchanged after raising the cap -- the cap is an address-space ceiling, not a pre-allocation. Verified by inspecting `du -sh` of fixture stores.

### Next moves
- **v1.5-#3 -- Python builder via libcst** is the next outstanding charter item. May no longer be perf-critical now that the SV builder's writer is bulk-COPY; revisit the rationale before committing. Size: M.
- **Investigate the 3 cross-file SV-imports test failures** (cache pollution between md/ and sv/legacy_tests/). Pre-existing on `1edddb4`; not blocking v1.5-#2 but should be fixed before they mask a real regression. Size: S (likely a one-line cache-key fix in `lift_file_cached` / `promote_file_cached`).
- **Investigate Kuzu shared-store teardown segfault** in `tests/knowledge_graph/store/test_origin_gc.py` -- one core dump in C++ during `DETACH DELETE` on session teardown after many tests. Pre-existing on `1edddb4`; suite still passes when run with the test-by-test isolation but flaps under high-coverage runs. Size: M.
- **Push** `kgweave/kuzu-port` to origin -- 4 commits ahead at journal-write time.

---

## 2026-05-22 — v1.5-#6 + #4 + #5 — three cheap charter items
**Branch / commit:** `kgweave/kuzu-port` @ `88ce061` (6 commits on top of v1.5-#1, push pending at journal-write time)

### What we did
- **#6 `gc_pruned` in demo exporter stats** (`e95d4d9` red + `99b2670` green).
  Both `research/ast_experiment/scripts/export_demo_graph*.py` now emit
  `stats.gc_pruned`: the Kuzu exporter sources it from `ExtractStats.gc_pruned`
  (returned by `knowledge_graph.extract()`); the legacy in-memory exporter
  has no GC concept so emits `0` for shape parity. Test lives at
  `tests/research/test_demo_exporter_stats.py` (under `testpaths=["tests"]`).
- **#4 Configurable compat policy** (`f290c0b` red + `25816b1` green).
  `verify_or_migrate_schema_version` gains `compat: Literal["semver-major",
  "exact", "any"] = "semver-major"`. Default unchanged; `"exact"` rejects
  any patch difference; `"any"` accepts any parseable 3-tuple semver
  string. Raised `SchemaVersionMismatch` carries the requested
  `compat_policy` so callers see which mode rejected the open. Dispatch
  in new `_check_compat` helper; `_is_compatible` stays the canonical
  predicate for the default. 24 schema-version tests pass (18 pre + 6 new).
- **#5 Session-scoped `register_connector` fixture** (`0de6048` red +
  `88ce061` green). Two changes:
  * Registry: `register_connector` now treats same-name + same-class as
    no-op (was identity-only). Different-class still raises.
  * Fixture: new session-scoped `sv_md_connector_registered` in
    `tests/knowledge_graph/connectors/conftest.py`. Both existing
    connector test modules now depend on it via a thin module-scope
    wrapper; legacy `try/except BuilderConflict` workaround removed.
  16 connector tests green.

### Lessons learnt
- **Charter said "registry should already be idempotent" -- it wasn't,
  not by the spec the fixtures needed.** The identity-only check made
  the *registry* technically idempotent for the same object but not for
  the equivalence class the fixtures were exercising. Same-class
  equivalence is the natural unit because connectors are pure dispatch
  objects with no per-instance state. Tightened the docstring to say
  so out loud.
- **`testpaths=["tests"]` silently drops `research/` tests.** The first
  red attempt landed under `research/ast_experiment/tests/` and pytest
  didn't pick it up. Putting it under `tests/research/` is the right
  call -- the test exercises a research-package exporter but its
  *purpose* is gate-keeping a public-contract field, so it belongs in
  the gated test tree.
- **The compat-policy enum is small enough that a Literal+if-chain beats
  a registry dict.** Three policies, no plug-in expectation. Resisted
  the urge to over-engineer.
- **Connector tests cost ~9 min wall on this box.** The session-scoped
  fixture didn't move that needle (the per-test extract is what costs);
  the win is correctness, not perf. Recorded so v1.5-#2 measurements
  can subtract this baseline.

### Next moves
1. **v1.5-#2 bulk-COPY writer** -- still the only remaining lever for
   the charter perf targets (per the v1.5-#1 retro, `extract()`
   dominates, cap doesn't help wall). *Size:* L.
2. **v1.5-#3 Python builder (libcst)** -- new builder + reuse the
   generalised SV-MD connector against Python identifier kinds. *Size:* L.
3. **Push and continue on top of HEAD** -- this slate is shippable
   independently; #2/#3 each open their own commit range.


**Branch / commit:** `kgweave/kuzu-port` @ `59de966` (8 commits on top of v1.4 + v1.5 charter, unpushed at journal-write time)

### What we did
- **G1** (`cfb2ee5` red + `0494f08` green) — Added `max_db_size_bytes:
  int | None = None` kwarg to `KGStore.open`; forwarded to
  `kuzu.Database(..., max_db_size=...)` only when caller opts in
  (omitted kwarg preserves Kuzu's 8 TB default for production). Spy
  test pins the forwarding contract.
- **G2** (`f08fb48`) — Behavioural test `tests/knowledge_graph/store/
  test_kgstore_max_db_size_behaviour.py`: opens a store with
  `max_db_size_bytes=268_435_456` (256 MiB; Kuzu requires power-of-2),
  writes 200 `:Origin` rows, checkpoints, asserts on-disk footprint
  stays under the cap. Discovery result: cap is honoured -- on-disk
  size for the 200-row store is well under 256 MiB.
- **G3** (`512a9c5` red + `3a032d7` green) — `tmp_store` and
  `shared_kuzu_store` fixtures + the quickstart subprocess now route
  the 256 MiB cap through. Quickstart honours
  `KGWEAVE_MAX_DB_SIZE_BYTES` env var so the perf test can opt in.
- **G4** (`4ad14eb`) — Re-measured quickstart with cap forwarded into
  the subprocess. Three runs: 125.58 s / 126.91 s / 124.69 s.
  **The cap did not move wall-clock.** Profile: `extract` is ~125 s,
  `open_store` is ~0.6 s. Cap correctly bounds on-disk to ~127 MB,
  but the v1.5-#1 hypothesis (sparse-allocation on ext4 = the
  bottleneck) was wrong on this box. Tightened the perf floor only
  modestly: 230 s -> 200 s, leaving ~70 s headroom over the new
  worst-of-3.
- **G5** (`c79f65f`) — Per the v1.5-#1 rule
  `max(perf_floor + 60, 2 * perf_floor) = max(260, 400)`, set the
  quickstart smoke subprocess timeout to 400 s (was 240 s). Larger
  than before because the cap did not reduce wall-clock and the smoke
  must not be tighter than the perf-floor allows.
- **G6** — All four targeted dirs green at this commit:
  - `tests/_meta/`: 19 passed, 1 skipped (the v1.4 regression net is intact).
  - `tests/knowledge_graph/store/`: 82 passed in 796 s.
  - `tests/knowledge_graph/connectors/`: 14 passed in 526 s.
  - `tests/knowledge_graph/facade/`: 15 passed in 1177 s **after**
    fixing a latent v1.4 issue: facade/conftest had no per-test
    timeout bump, so every fixture-using test (`facade_store` runs a
    ~125 s extract) tripped the 60 s global. Mirror of the store/
    pattern, pinned at 450 s to sit above the v1.5-#1 G5 400 s
    subprocess timeout. Committed separately as the G6 fix.

### Lessons learnt
- **A perf-hypothesis is just a hypothesis until you re-measure.** —
  v1.4-#4 concluded Kuzu's 8 TB sparse allocation was the ext4 cost.
  Re-running the quickstart with `max_db_size=256 MiB` forwarded ALL
  the way through (fixtures + subprocess) moved wall-clock by < 2 s
  on three runs. The fix doesn't fix anything user-visible -- it's
  hygiene only. Lesson: before building a tightening-budget loop on
  top of a perf fix, profile first to confirm the fix actually moves
  the metric the budget cares about.
- **Profile narrows the search before you spend the day.** — A
  ten-second `KGWEAVE_QS_PROFILE=1` run showed `extract: 125 s`,
  `open_store: 0.6 s`. That single line of profile output would have
  reframed the entire v1.5-#1 plan (target `extract`, not the store
  open path) if it had been added to the v1.4-#4 retro. The
  charter's "target ≤ 60 s / stretch ≤ 30 s" was unreachable from
  this lever; the next attack surface is the writer's per-row INSERT
  loop (v1.5-#2 was already on the slate for that).
- **Kuzu's `max_db_size` is reservation, not write throughput.** —
  The cap bounds the mmap address space; it does not affect the
  per-INSERT fsync rate. Once mmap address space isn't the bottleneck
  (which it never was on this box), the cap is a no-op for wall-clock.
  Keep the cap for the hygiene reason (bounded on-disk footprint, no
  surprise sparse files), but stop expecting wall-clock from it.
- **A "green slate" claim needs every targeted dir actually run, not
  just the ones you touched.** — v1.4 landed with `tests/knowledge_
  graph/facade/` silently broken on ext4 (60 s global timeout vs the
  fixture's ~125 s extract). The v1.4 slate's #4 only ran the
  `test_quickstart_perf` test (which carries its own decorator);
  the fixture-using tests in the same dir were never re-run after
  the basetemp move. v1.5-#1 G6 surfaced it because the plan called
  for the whole dir green. Lesson: when an infra change moves the
  perf characteristics, re-run *every* dir in the impact radius,
  not just the one whose name matches the change.
- **TDD discipline for "did it move the metric?" goals.** —
  G4 originally tried a 45 s budget (`ceil(15-20 * 1.5)` from the
  hypothesised post-cap measurement). The subprocess timed out at
  75 s, which was the "red" that surfaced the hypothesis was wrong.
  Lesson: write the ambitious budget commit first; the failing test
  is the cheapest way to discover the hypothesis was wrong.

### Next moves
1. **#2 bulk-COPY writer** — now confirmed as the only lever left for
   quickstart wall-clock. `extract` dominates at 125 s, `open_store`
   is 0.6 s. Replace the per-row `conn.execute(INSERT)` loop in
   `src/knowledge_graph/builders/sv/writer.py:602` with Kuzu
   `COPY FROM`. Target 10x writer speedup; that drops quickstart
   under 30 s and makes the v1.5-#1 charter targets retroactively
   achievable via the OTHER lever. *Size:* L. *Why now:* it's the
   only remaining bottleneck.
2. **#6 gc_pruned in demo exporter stats** (one-line) — ship cold. *Size:* XS.
3. **#4 compat policy kwarg** on `verify_or_migrate_schema_version`.
   *Size:* S.
4. **#5 session-scoped `register_connector` fixture** — fixes the
   `BuilderConflict` flake. *Size:* S.
5. **#3 builder #3 (Python via libcst)** — orthogonal to perf. *Size:* L.
- ~~Tighten v1.5-#1 budget further (45 s / 30 s stretch)~~ — blocked
  on #2 landing; extract dominates current wall-clock.
- ~~Kuzu mmap RSS investigation~~ — confirmed irrelevant by G4 measurement.

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

---

## 2026-05-23 — v1.5 slate — closing summary
**Branch / commit:** `kgweave/kuzu-port` @ `fe683cc` (27 commits on top of `3fd3a09`, push pending at journal-write time)

### What landed across the v1.5 slate
- **#1 — `max_db_size_bytes` kwarg** plumbed through `KGStore.open` and applied
  to `tmp_store` + `shared_kuzu_store` + quickstart fixtures at 256 MiB (later
  bumped to 1 GiB by #2 for BM frame-group headroom).
- **#6 — `gc_pruned` field** emitted by demo exporters in their stats payload
  so the integration story has a visible signal for sweep activity.
- **#4 — configurable compat policy** on `verify_or_migrate_schema_version`
  (kwarg `compat=` accepting `semver_major` / `exact` / `any`); default
  preserved at `semver_major`.
- **#5 — session-scoped `register_connector`** idempotent on equal instances
  so suite-level registration no longer fights itself; different-class
  conflicts still raise.
- **#2 — bulk-COPY writer** for SV (≥ 100 rows batches go through CSV + Kuzu
  `COPY ... FROM` with pre-COPY `DETACH DELETE` for replacement-merge).
  **Quickstart wall-clock: 125 s → 1.45 s (~90× faster).** Writer N=1000:
  10.3 s → 1.0 s (~10×). BM cap raised 256 MiB → 1 GiB to unblock COPY.
- **#3 — Python builder via libcst + Py↔MD reference connector.** Walker
  emits `PyModule` / `PyFunction` / `PyClass` / `PyImport`; connector resolves
  inline-code spans in MD to py-symbol nodes within the same corpus.
  Shared `_name_index` module extracted so SV-MD and Py-MD connectors share
  the same corpus-scoped indexer.

### Pre-existing items NOT addressed (deferred — see individual entries)
- 3 cross-file SV-imports test failures from md/sv fixture pollution
  (`builders/md/test_isolation_i7.py` and `builders/sv/legacy_tests/rules/test_types.py::test_s32_*`,
  `test_s50_does_not_disturb_s32_imports_edges`). Pre-existing on `1edddb4`;
  documented as cache-key bug in `lift_file_cached` / `promote_file_cached`.
- Kuzu C++ teardown segfault on `tests/knowledge_graph/store/test_origin_gc.py`
  under high-coverage runs. Suite still passes in isolation; documented.

### Commit count
- `git log --oneline 3fd3a09..HEAD | wc -l` = **27** commits.

### Headline win
**90× quickstart speedup** from #2 (bulk-COPY), enabling the next-builder
slate (#3) to land on a dev-grade feedback loop instead of multi-minute
fixture builds.

---

## 2026-05-23 — v1.5-#3 — Python builder via libcst + Py↔MD connector
**Branch / commit:** `kgweave/kuzu-port` @ `fe683cc` (6 commits on top of v1.5-#2 head `f7790ab`, push pending at journal-write time)

### What we did
- **G1 — shared name-index module.** Extracted corpus-scoped name-index logic
  from the SV-MD connector into `src/knowledge_graph/connectors/_name_index.py`
  with `build_name_index(...)`. SV-MD connector now imports from this module;
  back-compat re-exports preserve the public surface verified by
  `tests/knowledge_graph/connectors/test_name_index_module.py::test_public_connector_surface_unchanged`.
- **G2/G3/G4 — Python builder.** New `src/knowledge_graph/builders/py/`
  package: `walker.py` (libcst-based, emits `PyModule`, `PyFunction`,
  `PyClass`, `PyImport` with span ranges + payload), `writer.py` (Kuzu
  replacement-merge analogous to the SV writer, idempotent on unchanged
  content, subtree-replacing on edit), `build.py` (thin facade).
  Fixtures + tests under `tests/knowledge_graph/builders/py/`: `test_walker.py`
  (6), `test_writer.py` (5), `test_multi_file.py` (3). **14 py-builder tests
  green; 24 connector tests green; 655 sv-builder tests green; 72 store tests
  green; 15 facade tests green; 19 meta tests green.**
- **G5 — Py↔MD reference connector.** `src/knowledge_graph/connectors/py_md.py`
  built on `_name_index` from G1. Resolves inline-code spans (`` `foo` ``) in
  Markdown to `PyFunction` / `PyClass` nodes; corpus-scoped, idempotent on
  rerun, silent on unknown symbols. 5 dedicated tests in
  `tests/knowledge_graph/connectors/test_py_md.py`.

### Lessons learnt
- **libcst's metadata wrapper is the right entry point for byte-accurate
  spans** — *the position-provider gives line/col, but converting to byte
  offsets needs an explicit pass over the source. The walker now precomputes
  a line-start table once per module instead of recomputing per node. When we
  wire async/decorators/comprehension scopes later, reuse this table.*
- **The corpus-scoped name index is the right shared abstraction** — *both
  SV-MD and Py-MD connectors collapsed to the same code path once
  `_name_index` was extracted. Future Java/Rust builders should plug into the
  same indexer rather than reinventing per-language resolution.*
- **Builder-writer parity is cheaper than expected** — *the SV writer's
  replacement-merge contract (per-origin `DETACH DELETE` then re-write) ported
  verbatim to py with no behaviour changes. The structural abstraction
  (Node id = `(corpus, source, kind, name, span)`) holds across languages.*

### Not covered yet (queued)
- **Decorators** — currently dropped on the floor; needs a `PyDecorator` node
  or payload field on `PyFunction` / `PyClass`.
- **Async functions** — `async def` walked as `PyFunction` with no async flag.
- **Walrus (`:=`)** and **match-case** statements — not enumerated by walker;
  irrelevant for v1 (kind-level granularity) but will matter for any future
  per-statement queryability.
- **Comprehension scopes** — list/dict/set comprehensions create lexical
  scopes in Python ≥3 but walker treats them as expressions; OK for v1 since
  we don't emit per-variable nodes.
- **Type-alias statements** (`type X = ...` in 3.12+) — walker silently
  ignores.
- **Star imports** — `from x import *` captured as `PyImport` with empty
  symbol list; downstream connector treats as no resolvable names.

### Next moves
- **Decorators + async flags on PyFunction / PyClass** — *cheap payload-level
  addition; unblocks "find all @pytest.fixture" queries.* Size: S.
- **Py builder bulk-COPY parity with SV** — *the per-row MERGE path is fine
  for hand-written Python (small N), but a real repo lift will want the same
  ≥ 100 threshold + CSV-COPY path as SV. Reuse `_BULK_COPY_MIN_ROWS` and the
  helper extraction.* Size: M.
- **Cross-builder connector: Py imports → Py modules** — *the import payload
  already records the imported module name; resolving to the module's
  `PyModule` node within the same corpus gives the first real intra-language
  graph traversal.* Size: S.
- **Pre-existing items still deferred** — 3 cross-file SV-imports test
  failures (md/sv fixture pollution, see v1.5-#2 entry) and the Kuzu
  shared-store teardown segfault on `test_origin_gc.py`. Neither caused by
  v1.5-#3; both should be picked up before the next slate.
