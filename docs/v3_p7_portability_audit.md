# V3 #7 Portability Audit (reconstructed)

## Status

Fixes landed; this doc was reconstructed post-PC-crash from the on-disk
diff and the two new portability test files. The audit covers the
"Tier 3 #5 — Symbol-grounded resolver portability" line item from
`docs/v3_backlog.md` (agent `a6ef656edb3222bd3`).

The scope of what shipped in this pass is narrower than the backlog
entry suggests: **two concrete OT-isms were lifted into `KGConfig`**,
each pinned by a portability test. Several other OT-isms were
identified during the audit but deferred (see "Still hardcoded" below).

## Assumptions lifted (with evidence)

### 1. Reset-vs-clock signal classification regex

- **File:line**:
  `src/kgweave/knowledge_graph/extraction/sv_connectivity.py:42-46, 80-101`
  (module-level `_DEFAULT_RESET_PATTERN` + `SlangHierarchyAnalyzer`
  constructor arg).
- **Was**: `(^|_)(rst|reset|por)(_|$)` baked in as the only mechanism
  the slang hierarchy walker had for distinguishing reset signals from
  clocks in `always_ff` sensitivity lists. ARM AXI–style names
  (`aresetn`, `nrst`, `sresetn`) silently fell through to the
  `clocked_by` branch and were misclassified as clocks.
- **Now**: configurable via the new
  `SlangHierarchyAnalyzer(reset_signal_pattern=...)` constructor argument,
  populated from `KGConfig.reset_signal_pattern`
  (`src/kgweave/knowledge_graph/common/types.py:271-278, 418-421`),
  which in turn round-trips through `KGConfig.from_env` via the
  `RAG_KG_RESET_SIGNAL_PATTERN` environment variable. Default remains
  the OT regex, preserving back-compat. Invalid regex strings log a
  warning and fall back to the default rather than raising.
- **Test**:
  `tests/knowledge_graph/test_reset_signal_pattern_portability.py`
  pinning all three layers (default-misses-aresetn unit, KGConfig
  round-trip, end-to-end synthetic `frobnicator_engine` module driven
  by `aresetn`).

### 2. Testplan SVA assertion-name prefix list

- **File:line**:
  `src/kgweave/knowledge_graph/extraction/testplan_extractor.py:54,
  178-201` (the module-level `_SVA_PREFIXES` default + the
  `TestplanExtractor.__init__` resolution chain).
- **Was**: `_SVA_PREFIXES = ("a_", "prim_", "aes_")` baked in as the
  only set of prefixes considered when normalising SVA assertion names
  during testplan ingestion. Non-OT codebases naming assertions
  `widget_check_a`, `frob_assert_xyz`, etc., would not normalise to a
  canonical form.
- **Now**: three-level resolution — explicit constructor arg
  `sva_prefixes=...` wins; otherwise `KGConfig.testplan_sva_prefixes`
  (`types.py:280-286, 422-425`) is consulted; otherwise the OT default
  applies. Loadable from env via `RAG_KG_TESTPLAN_SVA_PREFIXES`
  (comma-separated). OT default behaviour is preserved when the env
  var / config field is unset.
- **Test**:
  `tests/knowledge_graph/test_testplan_sva_prefixes_portability.py`
  pinning the default OT normalisation, the `KGConfig` field
  existence + env round-trip, and the constructor-override path on
  `TestplanExtractor`.

## Still hardcoded (deferred — see `docs/v3_backlog.md`)

Items the audit identified but did not lift in this pass:

- **`_SVA_SUFFIXES = ("_a", "_assert", "_check")`** — paired with
  `_SVA_PREFIXES` in `testplan_extractor.py:55`. Constructor accepts
  `sva_suffixes`, but there is no `KGConfig` field and no env binding
  yet. Most non-OT shops still use one of these three suffixes, so the
  blast radius is small; tracked under the same Tier 3 #5 backlog
  bucket.
- **OT-flavoured assertion-name special case** in
  `testplan_extractor.py:542` (`tail.startswith("prim_") and "assert"
  in tail`) — still a literal `prim_` substring check. Should fold
  into the configurable prefix list once that's promoted.
- **`prim_*` / `tlul_*` sub-instance handling commentary** in
  `sv_connectivity.py:270, 411, 425` and `parser_extractor.py:667` —
  comments call out OT primitive naming as the motivating case but
  the surrounding logic does not actually pattern-match on those
  prefixes (it auto-creates nodes regardless of name). Behaviour is
  already generic; the OT references are documentation, not code.
  Leaving the comments as-is.
- **`buildsys_dvsim.py:51`** OT chip cfg filename references
  (`chip_earlgrey_*`) — example strings in the docstring only; no code
  path keys on this. Deferred (V3 #12a, full dvsim token expansion,
  is the right place for it).
- **`buildsys_bazel.py:30`** `"opentitan_binary"` rule name is a real
  literal in the rule-kind list. OT-specific by nature of the Bazel
  ruleset; non-OT users on Bazel would extend the list. Tracked as a
  small follow-up under Tier 3 #5.
- **`testplan_normalizer.py:11,35`** — the LLM normalizer prompt is
  hardcoded to "OpenTitan-style HJSON". Not lifted. The output schema
  the prompt targets (testpoints/covergroups) is structurally generic,
  but the framing tokens steer the LLM. Deferred.
- **Vendor-macro / conditional-compilation awareness** (backlog entry
  Tier 3 #5 sub-bullets `AES_BASE_ADDRESS` no-underscore variants and
  `#include` inside `#if 0`) — out of scope for this pass; needs a
  preprocessor and is jointly scoped with V3 #12.

## Generic-portability gap analysis

For the remaining OT-isms above, the generic anchors they should
eventually reach are:

- **SVA suffix list**: SystemVerilog LRM does not standardise
  assertion-name suffixes — the convention is purely cultural. The
  right anchor is "user-supplied list with a sensible OT-shaped
  default", same shape as the prefix lift. Promote to `KGConfig`
  symmetrically with the prefix field.
- **`prim_`/`assert` substring in `testplan_extractor.py:542`**:
  fold into the configurable prefix/suffix pair so the special case
  disappears; SVA naming convention is the only honest anchor.
- **dvsim chip cfg tokens**: project-conventions YAML (V3 #12a) — the
  generic spec is "every dvsim deployment defines its own
  `{proj_root}`-style tokens". No upstream LRM/standard exists.
- **Bazel `opentitan_binary` rule kind**: anchor on the user's
  Bazel ruleset definition (rules_hdl, rules_verilog, or vendor
  forks). Caller-supplied list of "binary-like" rule kinds is the
  right shape.
- **Testplan normalizer LLM prompt**: anchor on the documented HJSON
  testplan schema (testpoints / covergroups / milestones) rather than
  the OT codebase. The schema is generic; only the prompt phrasing
  needs decoupling.
- **Vendor macros / `#if 0`**: needs a real SV preprocessor pass
  (slang already provides one — re-use `pyslang.Preprocessor` rather
  than rolling regex heuristics). Tracked under V3 #12.

## Additional (incidental) changes observed in the diff

The `sv_connectivity.py` rewrite is far larger than the portability
fix — the file was simultaneously migrated from `pyverilog`'s
`DataflowAnalyzer` to a `pyslang.Compilation`-backed
`SlangHierarchyAnalyzer` and grew clock/reset-domain entity emission,
hierarchy walking, `connects_to` with elaborated paths, and assertion
extraction. This is unrelated to the V3 #7 portability brief but
shipped in the same commit window. Schema-side, `Entity`/`Triple`
gained `layer`, `attributes`, `confidence_tier`, `lhs_slice`,
`port_direction`, and a new `LayerDiff` dataclass
(`common/schemas.py`) — also out of V3 #7 scope but visible in the
diff. Flagging here so the audit trail is honest about what the
commit actually contains; only the two lifts above are the V3 #7
deliverable.
