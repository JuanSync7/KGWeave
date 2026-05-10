# Orphan RTL_Module Analysis (OpenTitan AES demo)

## Context

`parser_extractor` emits one `RTL_Module` entity per `module <name>` declaration
in every .sv file on the filelist. `SlangHierarchyAnalyzer` then runs a full
elaboration starting from `top_module="aes"` and emits `instantiates` edges
only for modules slang actually reaches. After Gap #1 landed, `bound_into`
edges connect bind-source modules to `aes`.

The result is that any RTL_Module the parser emitted but slang didn't reach
(and that isn't a bind source) sits as a zero-inbound node and clusters into
its own community in force-directed layouts.

## Numbers (current AES demo state)

| Metric | Value |
|---|---|
| Total RTL_Module entities | 38 |
| Reachable from `aes` via `instantiates` (out) + `bound_into` (in) | **5** |
| Unreachable (target of fix) | **33** |

The 5 reachable are: `aes`, `aes_core`, `aes_idle_check`, `aes_reseed_if`,
`aes_masking_reseed_if`. Note that many modules slang actually instantiates
(e.g. `prim_lc_sync`, `tlul_cmd_intg_chk`) come back as `concept`-typed
nodes because their .sv source isn't on our filelist — so they don't show up
as RTL_Module.

## Bucket distribution (33 unreachable)

| Bucket | Count | Description |
|---|---|---|
| A — defined-but-unused / library | 2 | `aes_ctr_fsm_n`, `aes_ctr_fsm_p` (parameter-selected variants of the ctr FSM, only one is wired in) |
| B — referenced in RTL but slang skipped | 27 | majority — slang did emit instantiates edges for these between RTL_Modules, but their immediate parent isn't itself reachable from `aes` (chain breaks above) |
| C — param-rename mismatch | 3 | `aes_ghash_wrap`, `aes_reduced_round`, `aes_wrap` — declared but never instantiated by any module on the filelist |
| D — bind / synthetic | 1 | `aes_bind` (bind container; bind directives create `bound_into` edges from its inner sources, the wrapper itself is not bind-targeted) |

### Bucket A examples
- `aes_ctr_fsm_n`, `aes_ctr_fsm_p`

### Bucket B examples (5–10)
- `aes_cipher_control_fsm`, `aes_cipher_control_fsm_n`, `aes_cipher_control_fsm_p`
- `aes_control_fsm`, `aes_control_fsm_n`, `aes_control_fsm_p`
- `aes_ctr_fsm`, `aes_dom_dep_mul_gf2pn`, `aes_dom_dep_mul_gf2pn_unopt`
- `aes_dom_indep_mul_gf2pn`, `aes_dom_inverse_gf2p4`, `aes_dom_inverse_gf2p8`
- `aes_mix_columns`, `aes_mix_single_column`, `aes_prng_masking`
- `aes_sbox`, `aes_sbox_canright`, `aes_sbox_canright_masked`,
  `aes_sbox_dom`, `aes_sbox_lut`, `aes_shift_rows`

These modules are **legitimately** used (parser saw `aes_sbox` instantiated
inside e.g. `aes_cipher_core`'s body) but slang's elaboration tree from `aes`
didn't traverse all the way down — because the parents are alternate
implementations selected by a parameter (`SecSBoxImpl`) and only one variant
is on the elaborated path.

### Bucket C examples
- `aes_ghash_wrap`, `aes_reduced_round`, `aes_wrap`

### Bucket D examples
- `aes_bind`

## Root cause for Bucket B

The `_n` / `_p` / `_canright` / `_dom` / `_lut` / `_masked*` modules are
**alternate implementations** chosen at elaboration time via parameters
(`SecSBoxImpl`, `SecMasking`, `SBoxImpl`, etc). The demo elaborates exactly
one combination, so 80% of the alternative implementations are filelist-
present but tree-absent. They aren't bugs in the extractor — they're
**genuine completeness-audit signal**: "you have N implementations on disk;
this build wires exactly one of them in."

## Fix decision

Per `docs/VISION.md` ("completeness audit, not validation"), orphans ARE
the audit signal. Deleting them would erase exactly the information the
audit needs to surface. So we **tag** them rather than delete.

Implementation: Option A — `reachable_from_top` post-pass on the backend,
written into RTL_Module aliases as `reachable=true|false`, surfaced in the
sigma export by muting unreachable nodes (gray-blue, 60% opacity, still
clickable).
