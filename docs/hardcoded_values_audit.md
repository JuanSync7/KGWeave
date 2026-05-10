# Hardcoded Values Audit

## Status: CLOSED — all 18 findings addressed (Phase 1–4)

The hardcoded-values cleanup landed across four phases. Every BLOCKER and
DEGRADED finding is now backed by a `ProjectConventions` field consumed by the
relevant extractor or reader; the OT profile is fully reproduced via
`ProjectConventions.opentitan()`. Strict-generic mode
(`KGConfig(project_conventions=ProjectConventions())` plus user-supplied
overrides) is exercised end-to-end in
`tests/knowledge_graph/test_generic_codebase_e2e.py`.

### How to use on a non-OpenTitan project

Construct `KGConfig(project_conventions=ProjectConventions(...))` populating
the fields that match your codebase (Bazel/Makefile/SV reset/clock/CSR-API
patterns, etc.) — see `tests/knowledge_graph/test_generic_codebase_e2e.py`
for a worked example covering Bazel `//rtl/<mod>:`-style deps,
`regress-<mod>:` Makefile targets, ARM AMBA-flavoured `pclk`/`presetn`
signals, and a custom `<mod>_csr_write32(...)` MMIO API.

## Post-cleanup verification

- **Final pytest count**: 753 passed / 1 skipped in `tests/knowledge_graph/`;
  821 passed / 2 skipped across the full `tests/` suite.
- **AES demo (`scripts/demo_opentitan_aes.py`)**: locked at 67/41/229/216/109
  (RTL coverage gaps / transitive gaps / SW_Test entities / tests_module
  edges / accesses_csr edges).
- **Greppable OT-name sweep in `src/kgweave/`**: every remaining hit lands in
  one of three permitted buckets:
  - `common/types.py` `ProjectConventions.opentitan()` classmethod (OT
    profile constants — by design).
  - `common/sw_test_config.py` `OPENTITAN_DEFAULT_PATTERNS` /
    `_opentitan_defaults()` / `OPENTITAN_DEFAULT_TEST_MARKERS` (back-compat
    OT defaults reachable only when `profile="opentitan"` or no
    `ProjectConventions` is supplied at all).
  - `extraction/buildsys_bazel.py` `DEFAULT_RULE_ALLOWLIST` /
    `DEFAULT_DEP_MODULE_PATTERN` (legacy back-compat fallbacks for naked
    `BazelBuildReader()` construction; ignored when `project_conventions`
    is supplied).
  - Docstrings/comments that mention OpenTitan as an example of where a
    given convention originates (no behavioural impact).
- **Legacy back-compat surfaces preserved**: bare `SWTestExtractor()`,
  `BazelBuildReader()`, `MakefileReader()` etc. constructed without
  `project_conventions` keep producing the OT-shaped behaviour exactly as
  before Phase 1.

Goal: identify every project-specific hardcoded value in `src/kgweave/` blocking
generic reuse on non-OpenTitan SystemVerilog/UVM/build-system projects.

Scope: read-only sweep of `src/kgweave/**/*.py`. Findings in `docs/`, illustrative
comments, and test fixtures are excluded per audit brief.

## Summary

- **Total findings: 18** — **5 BLOCKER**, **9 DEGRADED**, **4 COSMETIC**
- **Files most affected:**
  1. `src/kgweave/knowledge_graph/extraction/sw_test_extractor.py`
  2. `src/kgweave/knowledge_graph/common/sw_test_config.py`
  3. `src/kgweave/knowledge_graph/extraction/buildsys_bazel.py`
  4. `src/kgweave/knowledge_graph/extraction/buildsys_makefile.py`
  5. `src/kgweave/knowledge_graph/extraction/buildsys_fusesoc.py`
- **Recommended fix order (top 5 highest-impact):**
  1. Make Bazel `dep_module_pattern` and rule allowlist mandatory in
     `KGConfig.project_conventions` so non-OT projects don't silently lose every
     test→module link from BUILD files.
  2. Make `SwTestResolutionConfig` patterns project-pluggable and
     **omit defaults entirely** when `KGConfig.project_conventions` is supplied
     — current defaults pollute confidence on non-DIF codebases.
  3. Promote `reset_signal_pattern` from KGConfig field to a paired
     `clock_signal_pattern` so always_ff classification works for ARM `aresetn` /
     `aclk` codebases.
  4. Promote SW MMIO API regex (`mmio_region_*`, `abs_mmio_*`) and CSR offset
     suffix list (`_REG_OFFSET`, `_OFFSET`) to config — currently hardcoded in
     `sw_test_extractor.py`.
  5. Make `MakefileReader` variable name set (`MODULE`/`IP_NAME`/`IP_TOP`/
     `DUT`/`DUT_NAME`) and `_MODULE_FROM_CORE_RE` strip-suffixes
     (`_sim|_tb|_test|_dv`) configurable.

## Findings by category

### Path prefixes

| File:line | Value | Severity | Suggested fix |
|---|---|---|---|
| `extraction/buildsys_bazel.py:48` | `^//hw/ip/(?P<module>[a-z][a-z0-9_]*)\b` baked into `DEFAULT_DEP_MODULE_PATTERN` | **BLOCKER** (✓ Phase 2) | Already overridable via `bazel_dep_module_pattern` on `SwTestBuildSystemConfig`, but the *default* is OT-shaped. For a non-OT project that doesn't supply a YAML, every `//rtl/<mod>:`/`//src/<mod>:` dep silently fails to link → zero `tests_module` edges from Bazel. Make this `Optional` with no default and refuse to enable bazel reader without a configured pattern, OR move default into a project profile. |

### Rule-name defaults

| File:line | Value | Severity | Suggested fix |
|---|---|---|---|
| `extraction/buildsys_bazel.py:27-35` | `DEFAULT_RULE_ALLOWLIST = ["opentitan_functest","opentitan_test","opentitan_binary","cc_test","cc_binary","dv_lib","dv_fusesoc_test"]` | **DEGRADED** (✓ Phase 2) | The three `opentitan_*` rules are dead names on non-OT projects. `dv_fusesoc_test`, `dv_lib` are also OT-flavoured. The auto-discovery via `load()` mitigates this somewhat. Fix: split into `GENERIC_RULE_ALLOWLIST` (just `cc_test`/`cc_binary`) + `OPENTITAN_RULE_ALLOWLIST` overlay — `KGConfig.project_conventions.bazel_rule_allowlist` selects. |

### Module-name patterns

| File:line | Value | Severity | Suggested fix |
|---|---|---|---|
| `common/sw_test_config.py:128-155` | `OPENTITAN_DEFAULT_PATTERNS` — `dif_<mod>.h`, `dif_<mod>_*(` , `*_<MOD>_BASE_ADDR` | **BLOCKER** (✓ Phase 2) | These patterns presume OpenTitan's DIF C library naming. On a non-DIF project they match zero things AND cannot be replaced silently — `load_sw_test_config(None)` falls back to OT defaults. Fix: `KGConfig.project_conventions.sw_test_patterns: List[SwTestPattern]` with no default, plus an opt-in `_opentitan_defaults()` helper for OT users. |
| `common/sw_test_config.py:157-161` | `OPENTITAN_DEFAULT_TEST_MARKERS` — includes `OTTF_DEFINE_TEST_CONFIG` (OT-only macro) | **DEGRADED** (✓ Phase 2) | `int main(` and `void test_main(` are generic. `OTTF_DEFINE_TEST_CONFIG` is OT-specific but harmless extra match. Fix: same config field as above; the OT marker becomes part of an opt-in profile. |
| `extraction/sw_test_extractor.py:65-69` | `_MMIO_OFFSET_RE` matching `mmio_region_write32`/`abs_mmio_write32`; `_BARE_OFFSET_RE` requiring `_REG_OFFSET` suffix | **BLOCKER** (✓ Phase 3) | These OT-MMIO API names are baked into source. Non-OT C tests using `dev_write32(...)` or `iowrite32(...)` lose **all** `accesses_csr` edges. Fix: `KGConfig.project_conventions.csr_access_api_patterns: List[Pattern]` and `csr_offset_suffixes: List[str]` (default `("_REG_OFFSET","_OFFSET")`). |
| `extraction/sw_test_extractor.py:75, 451-457` | `_DIF_PATTERN_NAME = "dif_api_call"` plus synthetic `<mod>_dif_access` CSR name | **DEGRADED** (✓ Phase 3) | The pattern is config-driven but the *string* `dif_api_call` is hardcoded for the synthetic CSR side-effect. Fix: make synthetic emission opt-in via a `synthetic_csr_from_pattern: Optional[str]` config field. |
| `extraction/sw_test_extractor.py:481, 487` | Evidence-string formats `#include "dif_{module}.h"` and `dif_{module}_* call` | COSMETIC (✓ Phase 4) | Hardcoded strings appear only in evidence_span text — no behavior impact. |
| `extraction/buildsys_makefile.py:27-29` | `_VAR_RE = ...(MODULE|IP_NAME|IP_TOP|DUT|DUT_NAME)` | **DEGRADED** (✓ Phase 2) | The variable-name set is reasonable across many SoC Makefile flows but is conventionally OT/RTL-flavoured. Fix: `MakefileReader(module_var_names=[...])` constructor arg + `KGConfig.project_conventions.makefile_module_vars`. |
| `extraction/buildsys_makefile.py:31-33` | `_TEST_TARGET_RE = ^test[-_]<module>:` | **DEGRADED** (✓ Phase 2) | Conventional; doesn't match e.g. `regress-<module>:` or `sim-<module>:`. Fix: configurable target prefix list. |
| `extraction/buildsys_makefile.py:119` | `re.sub(r"_(top|dut|core|wrapper)$", "", val)` strip-suffix list | **DEGRADED** (✓ Phase 2) | Strip-suffixes are OT-RTL conventions. Fix: configurable list. |
| `extraction/buildsys_fusesoc.py:29` | `_TB_TARGET_HINTS = ("sim","tb","test","verilator")` | **DEGRADED** (✓ Phase 2) | Reasonable; misses `sve`, `xrun`, `vcs`, etc. Fix: configurable. |
| `extraction/buildsys_fusesoc.py:34-37` | `_RTL_ONLY_FILESET_NAMES = {"rtl","core",...}` and `_MODULE_FROM_CORE_RE` strip-suffix `_sim\|_tb\|_test\|_dv` | **DEGRADED** (✓ Phase 2) | Strip-suffix list is OT-flavoured. Fix: configurable. |
| `extraction/buildsys_uvm_testlist.py:27` | `_TB_SV_RE = ([A-Za-z_]\w*)_tb\.sv` | **DEGRADED** (✓ Phase 3) | `_tb.sv` convention is widespread but not universal (`*_tb_top.sv`, `*_testbench.sv`, `tb_*.sv`). Fix: configurable testbench-filename regex on `UvmTestlistReader`. |
| `extraction/dv_test_realization_extractor.py:40` | `_SUFFIXES_TO_STRIP = ["_vseq.sv","_test.sv",".sv"]` | **DEGRADED** (✓ Phase 3) | UVM convention but project-specific. Fix: constructor arg. |
| `extraction/testplan_extractor.py:54-55` | `_SVA_PREFIXES = ("a_","prim_","aes_")`, `_SVA_SUFFIXES = ("_a","_assert","_check")` | **DEGRADED** (✓ Phase 1/2) | `aes_` is OT-IP-specific. Already overridable via `KGConfig.testplan_sva_prefixes` (good) — but **default leaks `aes_`** as a generic SVA prefix, polluting normalization on any project where modules legitimately start with `aes_` and aren't AES. Fix: drop `aes_` from default; promote to opt-in profile. |

### Port/clock/reset conventions

| File:line | Value | Severity | Suggested fix |
|---|---|---|---|
| `extraction/sv_connectivity.py:46-47` | `_DEFAULT_RESET_PATTERN = r"(^\|_)(rst\|reset\|por)(_\|$)"` | **DEGRADED** (✓ Phase 1/2) | Already overridable via `KGConfig.reset_signal_pattern` (good). Default misclassifies ARM `aresetn`, `nrst`, `srst_n` codebases for `always_ff` clock-vs-reset distinction. The current default does include `rst` substring matches that catch most cases — but `aresetn` matches `rst`? Yes (`aresetn` contains `rst`). Verify boundary edges. |
| `extraction/sv_connectivity.py:1058-1070` (clock identifier scan) | No configurable clock-name pattern — clock detection relies on "everything in sensitivity list that doesn't match reset regex is a clock" | **DEGRADED** (✓ Phase 2) | Mostly works, but pairing reset with `clock_signal_pattern` would let users encode positive clock-name matching for ambiguous edges. Fix: add `KGConfig.clock_signal_pattern`. |

### Macro names

| File:line | Value | Severity | Suggested fix |
|---|---|---|---|
| `common/sw_test_config.py:160` | `OTTF_DEFINE_TEST_CONFIG` literal in default test markers | DEGRADED (counted above) (✓ Phase 2) | See `OPENTITAN_DEFAULT_TEST_MARKERS` finding. |
| `extraction/sv_connectivity.py:109-112` | Comment + behavior: bare `define` names like `INC_ASSERT` get auto-normalized to `=1` | COSMETIC (✓ Phase 4) | Auto-normalization is correct generic SV behavior; only the comment example is OT-flavoured. No code change needed. |

### Other

| File:line | Value | Severity | Suggested fix |
|---|---|---|---|
| `common/sw_test_buildsys.py:120-153` | `dvsim_hjson_glob = "**/*_cfg.hjson"`, `uvm_testlist_glob = "**/*.f"`, `fusesoc_glob = "**/*.core"`, `bazel_files = ["BUILD","BUILD.bazel"]`, `makefile_files = ["Makefile","makefile","*.mk"]` | COSMETIC (✓ Phase 4) | Already constructor-overridable on each reader and YAML-overridable. Defaults are generic/conventional. |
| `extraction/buildsys_bazel.py:213` | `srcs = [test_name + ".c"]` fallback when no `srcs` attribute | **DEGRADED** (✓ Phase 2) | Hardcodes `.c` extension assumption. Fix: configurable default suffix or skip emission. |
| `extraction/sw_test_extractor.py:201-203` | Restricts file walk to `.c` only — non-recursive (`iterdir()`) | **DEGRADED** (✓ Phase 3) | Non-recursive scan + `.c`-only excludes `.cc`/`.cpp` test files and any nested test layout. Fix: configurable extension list + recursion toggle, OR document `source` should already be a flat dir. |
| `common/types.py:283-286` | `KGConfig.testplan_sva_prefixes: Optional[List[str]] = None` defaulting to OT set | DEGRADED (counted above) (✓ Phase 1/2) | Already noted. |
| `common/sw_test_config.py:128-179` | All-up: `_opentitan_defaults()` is the fallback when no YAML supplied | **BLOCKER** (✓ Phase 2) | The "no config = OT behavior" model means a fresh non-OT user *must* know to write a YAML, and there's no schema validator. Fix: emit a runtime warning when defaults are used without explicit opt-in via `KGConfig.project_conventions.profile = "opentitan"`. |

## Suggested generic fix architecture

Consolidate via a single `ProjectConventions` dataclass on `KGConfig`:

```python
@dataclass
class ProjectConventions:
    # Identity / opt-in profile selection
    profile: Optional[str] = None  # "opentitan" loads OT-shaped defaults; None = strict generic

    # SV connectivity
    reset_signal_pattern: Optional[str] = None    # already on KGConfig — move here
    clock_signal_pattern: Optional[str] = None    # NEW

    # Testplan / SVA
    sva_prefixes: Optional[List[str]] = None      # already KGConfig.testplan_sva_prefixes
    sva_suffixes: Optional[List[str]] = None

    # SW test resolution (replaces sw_test_config.py defaults)
    sw_test_patterns: Optional[List[SwTestPattern]] = None
    sw_test_markers: Optional[List[str]] = None
    csr_access_api_patterns: Optional[List[str]] = None  # mmio_region_*, etc.
    csr_offset_suffixes: List[str] = field(default_factory=lambda: ["_REG_OFFSET", "_OFFSET"])
    sw_test_extensions: List[str] = field(default_factory=lambda: [".c"])
    synthetic_csr_from_pattern: Optional[str] = None     # was _DIF_PATTERN_NAME

    # Build-system readers
    bazel_rule_allowlist: Optional[List[str]] = None
    bazel_dep_module_pattern: Optional[str] = None       # already on SwTestBuildSystemConfig — promote here
    makefile_module_vars: List[str] = field(default_factory=lambda: ["MODULE","IP_NAME","IP_TOP","DUT","DUT_NAME"])
    makefile_test_target_prefixes: List[str] = field(default_factory=lambda: ["test-", "test_"])
    makefile_module_strip_suffixes: List[str] = field(default_factory=lambda: ["_top","_dut","_core","_wrapper"])
    fusesoc_tb_target_hints: List[str] = field(default_factory=lambda: ["sim","tb","test"])
    fusesoc_module_strip_suffixes: List[str] = field(default_factory=lambda: ["_sim","_tb","_test","_dv"])
    uvm_testbench_filename_regex: str = r"([A-Za-z_]\w*)_tb\.sv"

    # DV file→testplan fusion
    dv_test_file_strip_suffixes: List[str] = field(default_factory=lambda: ["_vseq.sv","_test.sv",".sv"])
```

Single `KGConfig.project_conventions: ProjectConventions = field(default_factory=ProjectConventions)`.
A new `ProjectConventions.opentitan()` classmethod returns the OT profile for
back-compat. All extractors and readers read from this dataclass via their
constructor; the existing per-extractor knobs (e.g. `reset_signal_pattern` arg)
remain for direct callers but read the conventions dataclass when not supplied.
Implementable as a single follow-up PR with a deprecation shim for the existing
`KGConfig.reset_signal_pattern` / `testplan_sva_prefixes` fields.
