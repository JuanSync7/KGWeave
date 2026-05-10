# SW→RTL test resolution — porting to non-OpenTitan codebases

The `SWTestExtractor` links SW regression tests (C source files) to the
RTL modules they exercise. As of V3 Tier A, the resolver is a generic
**config-driven pattern engine**: project teams supply a YAML file
describing their codebase's naming conventions, and the engine applies
those patterns instead of OpenTitan-specific hardcoded heuristics.

When no config is supplied, the engine falls back to the OpenTitan
default config, which replicates the original three signals exactly:

1. `#include "dif_<module>.h"` — DIF header includes.
2. `dif_<module>_<api>(...)` — DIF API calls.
3. `*_<MODNAME>_BASE_ADDR` — top-level base-address macros.

The default YAML lives at `config/sw_test_resolution.yaml` (see also
`src/kgweave/knowledge_graph/common/sw_test_config.py` for the in-Python
defaults that ship with the package).

## Config schema

```yaml
patterns:
  - name: header_include          # human-readable identifier
    description: "..."            # optional
    regex: '...(?P<module>...)...' # MUST include a (?P<module>...) named group
    confidence_tier: high          # high | medium | low — applied to emitted edge
    transform: none                # none | lowercase | uppercase

test_markers:
  - 'int\s+main\s*\('              # regex against file text; any match → is_test=True
  - 'OTTF_DEFINE_TEST_CONFIG\b'

preprocessor_strip_if_zero: false  # Tier C stub — not yet implemented
```

### Field semantics

- **`patterns`** — ordered list. Each pattern is tried; per `(test, module)`
  tuple, at most one `tests_module` edge is emitted. The first pattern to
  claim a module owns the edge's `confidence_tier`; later patterns on the
  same module contribute additional evidence-span fragments.
- **`regex`** — must contain a named group `(?P<module>...)` capturing
  the module name. The captured value is normalized via `transform` and
  resolved against the KG's known RTL module names. Resolution is
  case-insensitive in the fallback path, so configs that capture
  uppercase identifiers without an explicit `transform: lowercase`
  still hit the index.
- **`confidence_tier`** — propagates to the emitted triple's
  `confidence_tier` and drives the audit-precision view.
- **`transform`** — module-name normalization. `lowercase` is the most
  common: macro names like `AES_BASE_ADDR` capture as `AES`, but the
  KG stores modules as `aes`. Use `none` when the captured form already
  matches your KG canonical casing.
- **`test_markers`** — regex set; if any matches the file text, the
  emitted `SW_Test` entity has `is_test=True`. Files lacking any marker
  are still emitted as entities (with `is_test=False`) but do not
  trigger the unresolved-sentinel `<unknown>` edge.

### Edge-emission semantics

For each C file:

1. Scan with each pattern in declaration order; collect resolved modules.
2. Emit one `tests_module` edge per resolved module (deduped).
3. If `is_test=True` and no module resolved, emit the low-tier sentinel
   `tests_module → <unknown>` with `resolved=False`.
4. The `accesses_csr` scan (mmio/offset constants) is orthogonal to the
   pattern engine and remains hardcoded — Tier B work.

## Porting examples

### CamelCase project (no DIF prefix)

```yaml
patterns:
  - name: camel_base_address
    description: "aesBaseAddress, hmacBaseAddress, etc."
    regex: '\b(?P<module>[a-z][a-zA-Z0-9]*)BaseAddress\b'
    confidence_tier: high
    transform: lowercase

  - name: helper_call
    description: "myDevHelperEncrypt(aes_handle, ...)"
    regex: '\bmyDev(?P<module>[A-Z][a-zA-Z0-9]*?)(?:Encrypt|Decrypt|Init)\s*\('
    confidence_tier: medium
    transform: lowercase

test_markers:
  - '\bint\s+main\s*\('
  - '\bTEST_F\s*\('
```

### Vendor macro without underscore separator

```yaml
patterns:
  - name: vendor_base_addr
    regex: '\b(?P<module>[A-Z][A-Z0-9]*)_BASE_ADDRESS\b'
    confidence_tier: high
    transform: lowercase
```

### Function-naming convention only

```yaml
patterns:
  - name: hal_call
    description: "HAL_AES_Init, HAL_HMAC_Update, ..."
    regex: '\bHAL_(?P<module>[A-Z][A-Z0-9]*)_\w+\s*\('
    confidence_tier: high
    transform: lowercase
```

## Special pattern names

The pattern named **`dif_api_call`** triggers the legacy OpenTitan
Tier-2 heuristic: every module resolved through that pattern also
emits a synthetic `accesses_csr → <module>.<module>_dif_access`
edge. This name is reserved for backward compatibility; non-OpenTitan
configs without a `dif_api_call` pattern simply skip the synthetic.

## Loading a config

```python
from kgweave.knowledge_graph.common.sw_test_config import load_sw_test_config
from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor

cfg = load_sw_test_config("path/to/my_project_resolver.yaml")
ex = SWTestExtractor(known_entity_names=known_names, sw_test_config=cfg)
res = ex.extract(source="path/to/sw/tests")
```

Passing `None` (or omitting `sw_test_config`) returns the OpenTitan defaults.

## Tier B — build-system ingestion

Pattern-based resolution is a fallback. When a project exposes
*machine-readable* test→module links via its build system, those links
are **authoritative** — the build system actually compiles and runs the
code, so its declarations are far more reliable than regex matches over
C source. Tier B introduces a five-format reader registry that runs
**before** the regex engine and **overrides** any pattern match for the
same `(test_path, module_name)` pair.

### Five formats supported

| Reader name      | Default tier | What it parses                                                  |
| ---------------- | ------------ | --------------------------------------------------------------- |
| `dvsim_hjson`    | high         | OpenTitan/lowRISC `*_sim_cfg.hjson` regression configs.         |
| `uvm_testlist`   | medium       | UVM `.f` files with `+UVM_TESTNAME=...` and `*_tb.sv` paths.    |
| `fusesoc`        | high         | CAPI2 `*.core` YAML files (tb-style targets only).              |
| `bazel`          | high         | `BUILD` / `BUILD.bazel` rule calls (`opentitan_functest`, etc.) |
| `makefile`       | medium       | `Makefile` / `*.mk` `MODULE :=`, `IP_NAME ?=`, `test-<m>:`.     |

### Reader interface

Every reader implements `BuildSystemReader`:

```python
class BuildSystemReader(Protocol):
    name: str
    def applies_to(self, project_root: Path) -> bool: ...
    def read(self, project_root: Path) -> list[BuildSystemLink]: ...
```

`discover_links(project_root, readers=...)` aggregates output across the
registered readers. Readers that fail (malformed input, missing files)
log a warning and return `[]` rather than halting the pipeline.

### Per-format examples

**dvsim hjson** (OpenTitan):

```hjson
{
  name: aes
  dut: aes
  tests: [
    { name: aes_smoke uvm_test: aes_smoke_test }
  ]
}
```
→ `BuildSystemLink(test_path="aes_smoke", module_name="aes", tier="high")`.

**UVM testlist** (`aes_test.f`):

```
+UVM_TESTNAME=aes_smoke_vseq
${PROJ}/dv/aes_tb.sv
```
→ `BuildSystemLink(test_path="aes_smoke_vseq", module_name="aes", tier="medium")`
(module inferred from `aes_tb.sv` basename heuristic).

**fusesoc** (`aes.core`):

```yaml
CAPI=2:
name: lowrisc:dv:aes_sim:0.1
filesets:
  tb:
    files: [dv/tb.sv]
targets:
  sim: { filesets: [tb], toplevel: tb }
```
→ links from `dv/tb.sv` → `aes` (module derived from VLNV).

**Bazel BUILD**:

```python
opentitan_functest(
    name = "aes_smoketest",
    srcs = ["aes_smoketest.c"],
    deps = ["//hw/ip/aes:aes_pkg"],
)
```
→ link from `aes_smoketest.c` → `aes` (extracted from `//hw/ip/<module>:`).

**Makefile**:

```make
MODULE := aes
SRCS = aes_test.c
test-aes: $(SRCS)
```
→ link from `aes_test.c` → `aes`.

### Enabling readers

Add a `build_systems:` block to your `sw_test_resolution.yaml`. All
readers default-disabled; opt in per format:

```yaml
build_systems:
  dvsim_hjson:
    enabled: true
    glob: "**/*sim_cfg.hjson"
  bazel:
    enabled: true
    files: ["BUILD", "BUILD.bazel"]
    # Optional. Regex applied to each Bazel deps label to extract the
    # owning RTL module. MUST contain a (?P<module>...) named group.
    # Default: '^//hw/ip/(?P<module>[a-z][a-z0-9_]*)\b' (OpenTitan).
    # Override for projects with a different layout, e.g.
    # dep_module_pattern: '^//rtl/(?P<module>[a-z][a-z0-9_]*)\b'
  uvm_testlist:
    enabled: false
    glob: "**/*.f"
  fusesoc:
    enabled: false
    glob: "**/*.core"
  makefile:
    enabled: false
    files: ["Makefile", "makefile", "*.mk"]
```

The OpenTitan-flavored config that ships with KGWeave enables
`dvsim_hjson` and `bazel`.

### Resolver integration

`SWTestExtractor.extract()` now accepts `project_root` and
`build_system_readers` parameters:

```python
ex = SWTestExtractor(
    known_entity_names=names,
    sw_test_config=load_sw_test_config("path/to/sw_test_resolution.yaml"),
)
res = ex.extract(
    source="sw/device/tests",
    project_root=Path("opentitan/"),  # Tier B: enables build-system readers
)
```

When `project_root` is `None`, **behavior is byte-identical to
Tier A** — readers don't run, only patterns. This preserves backward
compatibility for callers that don't yet emit a project root.

### Precedence rules

For each `(test_path, module_name)` pair:

1. Build-system links emitted first (high or medium tier; preserved as
   `attributes={"build_system_format": ..., "build_system_source": ...}`).
2. Regex pattern matches scanned next; any match for a module already
   covered by a build-system link is **suppressed**.
3. Regex matches for *other* modules (not covered by the build system)
   are kept — build systems can be incomplete.

The emitted `Triple` carries the build-system provenance in both its
`evidence_span` (`"dvsim_hjson:aes_sim_cfg.hjson -> aes in aes_smoke.c"`)
and its `attributes` dict.

### Cross-referencing test paths

Build-system readers emit `test_path` in whatever form is natural for
the format (basename for dvsim, full path for fusesoc / Bazel). The
extractor matches against on-disk C files via three keys: absolute
resolved path, filename basename, and stem (basename without
extension). dvsim's `name: aes_smoke` matches `aes_smoke.c` via the stem
fallback.

### Limitations

- **Bazel macro expansion is not done.** Only direct rule calls in the
  BUILD file are seen. If a test is wrapped in `load(..., my_macro)` /
  `my_macro(...)`, the underlying rule is invisible until you add
  `my_macro` to the rule allowlist (`rule_allowlist` argument on
  `BazelBuildReader`). OpenTitan's commonly-used rule kinds
  (`opentitan_functest`, `opentitan_test`, `cc_test`, etc.) ship in the
  default allowlist.
- **Makefile variable expansion is not done.** Values like
  `MODULE := $(SOMETHING)` are skipped (no module extracted). The
  Makefile reader is intentionally heuristic — confidence tier `medium`.
- **Bazel macro auto-discovery is conservative.** See `bazel_auto_discover_loaded_macros`
  / `bazel_loaded_macro_denylist` for tuning.

### dvsim `import_cfgs:` recursive resolution (V3 #2)

Real OpenTitan layouts use chip-level cfgs (`chip_earlgrey_asic_sim_cfg.hjson`,
`chip_sim_cfg.hjson`) that contain only `import_cfgs:` lists pointing to
per-IP cfgs and carry no `tests:` block of their own. Without recursion
those chip cfgs contribute zero links. The dvsim reader now follows
`import_cfgs:` transitively:

- **Path resolution.** Bare relative paths resolve against the importing
  cfg's parent directory. The `{proj_root}` token expands to the
  `project_root` passed to `read()`. Other dvsim tokens
  (`{dv_root}`, `{top_dv_path}`, `{tool}`, …) are NOT expanded — paths
  containing those tokens are skipped with a warning.
- **Cycle protection.** A visited-set keyed on the resolved absolute
  path prevents infinite loops; a cycle is logged at `WARNING` and the
  recursion branch terminates.
- **Depth limit.** Default `dvsim_max_import_depth=5` (configurable via
  the `build_systems.dvsim_hjson.max_import_depth` YAML key). Branches
  exceeding the limit are dropped with a warning.
- **Union semantics.** A cfg with both its own `tests:` and
  `import_cfgs:` emits its own tests first, then recurses. Both sets of
  tests reach the resolver.
- **Provenance.** Tests reached via recursion carry two extra
  `BuildSystemLink.raw_match` keys (mirrored to `attributes` when the
  field is available):
  - `dvsim_import_chain`: list of cfg paths from the entry-point cfg
    down to the cfg the test is defined in (most recent last; length ≥ 2
    for transitive entries).
  - `dvsim_root_cfg`: the original entry-point cfg path.
  The `source_file` field continues to point at the cfg the test was
  *defined in*, so downstream `build_system_source` attribution remains
  the most-specific provenance.
- **Missing imports.** Targets that don't exist on disk produce a
  `WARNING` and are skipped; sibling imports continue resolving.

## Deferred work

- **Tier C — `#if 0` preprocessor handling.** The
  `preprocessor_strip_if_zero` flag exists in the schema but is not yet
  implemented. Pattern matches inside `#if 0 ... #endif` regions are
  currently treated the same as live code.
- **Macro / `load()` expansion in Bazel.** Today only direct rule calls
  are parsed; tests wrapped in user macros need their wrapper added to
  the rule allowlist.
- **Variable expansion in Makefiles.** Same heuristic limitation —
  values referencing other make-vars are skipped, not expanded.
