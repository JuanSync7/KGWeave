# KGWeave Genericness Auto-Research — Changelog

**Branch:** `autoresearch/genericness-2026-05-10`
**Date:** 2026-05-10
**Outcome:** Success — score 9 → 0, guard PASS throughout.

## What improved

| Iter | Commit  | Score | Strategy |
|------|---------|-------|----------|
| 001  | `c8e8aec` | 9 → 9 | baseline (post hardcoded-values audit) |
| 002  | `d20cab1` | 9 → 7 | Lift behavior-controlling module-level OT defaults into permitted zones (`OPENTITAN_*`-named constants) |
| 003  | `2a61574` | 7 → 2 | Centralize `OPENTITAN_PROFILE = "opentitan"` constant in `common/types.py`; replace bare-string profile comparisons; refactor user-facing warnings to `%s` + constant |
| 004  | `b53f3b9` | 2 → 0 | Genericize LLM prompt templates: replace `aes_cipher_core` with `example_module`; drop "OpenTitan-style" qualifier from testplan-normalizer prompt |

**+8 tests added** across the loop (2 in iter-002, 4 in iter-003, 2 in iter-004) — all green.
**AES demo bit-stable** through every iteration: `67 / 41 / 229 / 216 / 109`.

## What didn't work / wasn't tried

The loop hit the success target without exhausting strategies. No revert
events occurred. Notable items deliberately left out of scope:

- The historical 18 findings catalogued in `docs/hardcoded_values_audit.md`
  remained closed; this loop only addressed residual hits the new scorer
  surfaced (which the prior cleanup couldn't see because its grep was less
  precise about permitted zones).
- LLM prompt-quality regression for the `testplan_normalizer` and
  `spec_claim_extractor` changes is not directly verified by the guard. The
  AES demo bit-stability check exercises real extraction paths but does not
  invoke the LLM prompt path. If a downstream user reports prompt drift, the
  reverts are isolated to two well-tested strings.

## Remaining gaps

Score is 0 against the current scorer pattern set
(`opentitan|lowrisc|earlgrey|darjeeling|hw/ip/|tlul|prim_lc|prim_mubi|ottf|dif_*|aes_*|hmac_*|kmac_*|otp_ctrl`).

The scorer treats four zones as permitted:

1. Functions whose name contains `opentitan` (e.g. `_opentitan_defaults`).
2. Module/class constants whose name contains `OPENTITAN`.
3. Docstrings (incl. PEP-257 attribute docstrings).
4. `# noqa: ot-ref` tags (none currently used — every site was either
   refactored into a permitted zone or genericized).

If new OT-specific defaults are introduced later, they must land inside one
of these zones or be tagged. The scorer + guard run cheaply (<2 min combined)
and can be wired into CI as a regression gate.

## Hypothesis vs outcome

- **Iter 002 hypothesis:** "rename to OPENTITAN_-prefixed constant — pure
  back-compat, no behavior change." → Confirmed exactly. Tests passed before
  AND after the rename. The renamed-constant approach is the cheapest fix
  shape — preferred over moving values into method bodies whenever the
  constant's lifetime is module-level by design.

- **Iter 003 hypothesis:** "centralize the profile string; expected score
  reduction 7 → 3." → Better than predicted (7 → 2). The five comparison /
  warning-string sites all collapsed in one pass; the predicted "3 remaining"
  miscounted (the testplan_normalizer hit was already isolated to its own
  category). Lesson: when one constant resolves a class of sites, count the
  *categories* not the individual sites.

- **Iter 004 hypothesis:** "genericizing the two prompt strings will reach
  zero." → Confirmed exactly. Both strings substituted cleanly; no prompt
  test regressed.

## Final state

- **Branch:** `autoresearch/genericness-2026-05-10` at `b53f3b9`
- **Score:** 0
- **Guard:** PASS
- **AES demo:** 67/41/229/216/109 (bit-stable)
- **Test suite:** all KG tests pass (+8 new this loop)
