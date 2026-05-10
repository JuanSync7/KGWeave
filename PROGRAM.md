# PROGRAM.md — KGWeave Regex/Fragile-String Auto-Research

## Objective

Drive the count of fragile, regex-based or literal-substring-based parsing
paths in the **extractor layer** to **zero**. The end-state goal is that no
extractor depends on `re.<func>` calls or on hardcoded substring/prefix/suffix
checks against source-code text — extractors must be parser-driven (tree-sitter
/ pyslang / AST) and resilient to arbitrary, malformed, or adversarial SV input.

The motivating concern: **"if I drop a random `.sv` file in, does it break?"**
A regex written for one project's coding style is dangerous on a different
project's code; a `.startswith("module ")` check fails on a file that uses
`module\tfoo` or a Verilog-2001 `endmodule` style. Parser-driven extraction
is the durable fix.

Strings against AST node-type names (e.g. `kind_str.endswith("Interface")`)
are **not** counted — they are robust by design because tree-sitter / pyslang
produce those names from a fixed grammar.

## Metric

**Mode:** Numerical, lower-is-better.

**Scorer:** `python scripts/regex_fragility_scorer.py` — emits JSON
`{"score": int, "by_kind": {...}, "hits": [...]}`. Score is the count of
unpermitted hits across `src/kgweave/knowledge_graph/extraction/`:

  1. `re.<func>(...)` calls — `compile, search, match, fullmatch, findall,
     finditer, sub, subn, split` (also matches `import re as _re`).
  2. `.startswith(literal)` / `.endswith(literal)` calls AND `"literal" in x`
     compares **only** when the receiver variable name suggests source-code
     text (e.g. `line, text, content, src, source, body, raw, code, snippet,
     chunk, token, value, val, expr, stmt, signal, name`) and does NOT
     contain a safe-receiver token (`kind, tag, type, node, rule, path,
     file, ext, suffix`).

**Permitted-zone marker:** `# noqa: regex-ok` on the same line, with a
one-line rationale in a comment above. Use sparingly — every use is a
debt entry; new ones should not be introduced unless the alternative is
genuinely worse than the regex.

**Baseline:** 92 (2026-05-10) — `re_module_call: 82, str_startswith: 7,
str_endswith: 3`.
**Target:** 0.

## Correctness guard (mandatory each iteration)

`bash scripts/regex_fragility_guard.sh` — exit 0 = pass. Verifies:

1. `pytest tests/knowledge_graph/ -x -q` green (full KG suite, including the
   new `test_sv_fuzz_resilience.py` — 28 adversarial inputs across the
   regex and SV-parser extractors).

A score reduction with a failing guard is **not** an improvement — revert.

## TDD discipline (loop-attached requirement)

Every kept iteration must include a **new or updated test** in
`tests/knowledge_graph/` that:

- **Was added/edited in the same commit as the fix** (no test-free changes).
- **Would have failed before the fix** — either by asserting the specific
  regex/literal is gone, or by asserting the new structural code produces
  the right output on a representative input the old regex got wrong.
- For changes touching SV-content extractors: extends `FUZZ_CORPUS` in
  `test_sv_fuzz_resilience.py` with at least one new adversarial input the
  old code crashed/misbehaved on. The new corpus entry must pass under the
  new code.

If a kept iteration introduces a code change without an accompanying test
delta meeting these criteria, revert.

## Mutable files

- `src/kgweave/knowledge_graph/extraction/*.py` (excluding `__init__.py`).
- `tests/knowledge_graph/*.py`.

## Immutable

- `scripts/regex_fragility_scorer.py` (the metric)
- `scripts/regex_fragility_guard.sh` (the guard)
- `tests/knowledge_graph/test_sv_fuzz_resilience.py`'s `FUZZ_CORPUS` entries
  may be **extended** but not weakened or removed; existing entries and the
  no-uncaught-exception assertion are immutable.
- `tests/knowledge_graph/test_generic_codebase_e2e.py` — generic non-OT
  fixture must keep passing; existing assertions immutable, may be extended.
- `src/kgweave/knowledge_graph/extraction/__init__.py` (public facade —
  changes here ripple to RagWeave callers)
- `PROGRAM.md` (this file)

## Exploration directions

In priority order:

1. **Replace `re.compile(...)` patterns with parser-driven equivalents.**
   For SV-content extractors (`sv_connectivity.py`, `regex_extractor.py`'s
   SV-targeting paths, `sv_v2_walker.py`), the substitute is pyslang AST
   walking. For build-system files (`buildsys_*.py`), the substitute is the
   format's official parser when available (e.g. `hjson` for HJSON,
   `tomllib`/`tomli` for TOML, real `make -dn` parse traces or a Make AST
   for Makefiles, structured Bazel query output for Bazel).

2. **Replace `.startswith(literal)` / `"x" in line` checks with structured
   parsing.** For each hit, ask: does the surrounding code already have a
   structural alternative (an AST node, a parsed config dict, a tokenized
   form)? If yes, switch to the structural form. If no, the fix is to
   introduce one — usually small (a 10–20-line tokenizer) and worth it.

3. **Lift unavoidable regexes into a single, well-tested helper module.**
   Some patterns truly are regex-shaped (e.g. matching a `$display("...")`
   format spec). When elimination is genuinely worse than centralization,
   move the pattern to a named constant in a permitted helper and call sites
   tag with `# noqa: regex-ok` plus rationale. Treat this as a last resort,
   not a default.

## Stop conditions

- **Success:** score reaches 0 AND guard passes AND every kept iteration
  carries a test delta meeting the TDD criteria. Stop and report.
- **Stuck:** 10 consecutive iterations with no score reduction → stop and
  report remaining hits with rationale.
- **Crash budget:** 3 consecutive crashes (guard or scorer failure) → stop
  and report.
- **Per-iteration budget:** if any single iteration takes more than 4
  consecutive subagent dispatches (incl. retries) without a kept commit,
  drop the strategy and move on.
