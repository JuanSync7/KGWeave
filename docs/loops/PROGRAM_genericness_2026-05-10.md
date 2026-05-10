# PROGRAM.md — KGWeave Genericness Auto-Research

## Objective

Drive the count of behavior-controlling OpenTitan-specific references in
`src/kgweave/` outside permitted zones to **zero**. Permitted zones are:

1. Functions/methods whose name contains `opentitan` (e.g. `ProjectConventions.opentitan()`,
   `_opentitan_defaults()`).
2. Module/class-level constants whose name contains `OPENTITAN`
   (e.g. `OPENTITAN_DEFAULT_PATTERNS`).
3. Docstrings (module/class/function/PEP-257 attribute docstrings).
4. `#` line comments.
5. Any line with the explicit allowlist marker `# noqa: ot-ref` and a one-line
   justification.

Every other OT reference must be removed, refactored into a permitted zone, or
explicitly tagged with `# noqa: ot-ref`.

## Metric

**Mode:** Numerical, lower-is-better.

**Scorer:** `python scripts/genericness_scorer.py` — emits JSON
`{"score": int, "hits": [...]}`. Score is the count of unpermitted matches of:
`opentitan, lowrisc, earlgrey, darjeeling, hw/ip/, tlul, prim_lc, prim_mubi,
ottf, dif_*, aes_*, hmac_*, kmac_*, otp_ctrl`.

**Baseline:** 9 (2026-05-10).
**Target:** 0.

## Correctness guard (mandatory each iteration)

`bash scripts/genericness_guard.sh` — exit 0 = pass. Verifies:

1. `pytest tests/knowledge_graph/ -x` green.
2. AES demo (`scripts/demo_opentitan_aes.py`) emits all five canonical numbers
   `67`, `41`, `229`, `216`, `109` (bit-stable invariant from prior cleanup).

A score reduction with a failing guard is **not** an improvement — revert.

## TDD discipline (loop-attached requirement)

Every kept iteration must include a **new or updated test** in
`tests/knowledge_graph/` that would have failed before the fix. The test must:

- Assert the specific OT-ism is absent OR the generic-mode behavior is correct
  on a non-OT fixture.
- Be added/edited in the same commit as the fix.

If a kept iteration introduces a code change without an accompanying test
delta, revert.

## Mutable files

- All Python sources under `src/kgweave/`
- All test files under `tests/knowledge_graph/`

## Immutable

- `scripts/genericness_scorer.py` (the metric)
- `scripts/genericness_guard.sh` (the guard)
- `scripts/demo_opentitan_aes.py` (the bit-stability anchor)
- `tests/knowledge_graph/test_generic_codebase_e2e.py` (the e2e fixture — may be
  *extended* with new assertions but not weakened; existing assertions immutable)
- `docs/hardcoded_values_audit.md` (closed historical record)
- `PROGRAM.md` (this file)

## Exploration directions

In priority order:

1. **Lift behavior-controlling module-level OT defaults into `ProjectConventions.opentitan()`.**
   `DEFAULT_DEP_MODULE_PATTERN` in `buildsys_bazel.py` and `_DIF_PATTERN_NAME` in
   `sw_test_extractor.py` are the obvious candidates. Replace module-level value
   with `None` (or generic default), thread the OT-specific value through the
   profile classmethod. Add a generic-fixture test that proves the strict-generic
   path no longer leaks the OT default.

2. **Centralize the profile identifier string.** Multiple
   `profile == "opentitan"` comparisons exist. Either introduce a single
   `OPENTITAN_PROFILE = "opentitan"` constant in a permitted zone and reference
   it (auto-allowlisted because the name contains OPENTITAN), or tag each
   comparison site with `# noqa: ot-ref` plus a one-line justification.

3. **Genericize LLM prompt templates** (`testplan_normalizer.py`,
   `spec_claim_extractor.py`). Prompts that say "OpenTitan-style HJSON" or use
   `aes_cipher_core` as an example can name the format/example generically
   without losing fidelity. Add a test asserting the prompt does not contain
   project-specific identifiers.

## Stop conditions

- **Success:** score reaches 0 AND guard passes AND every kept iteration carries
  a test delta. Stop and report.
- **Stuck:** 5 consecutive iterations with no score reduction → stop and report
  remaining hits with rationale.
- **Crash budget:** 3 consecutive crashes (guard or scorer failure) → stop.
