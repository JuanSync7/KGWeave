# Bucket 2 — Existing-Extractor Signal Inventory

Read-only audit of every Entity-type / Triple-predicate emitted by the
production KGWeave extractor pipeline at
`src/kgweave/knowledge_graph/extraction/`, classified for migration onto
the new `build_kg` pyslang-AST experiment.

All citations are `file:line` against the working tree at HEAD
(`autoresearch/regex-fragility-2026-05-10`, commit `6bb8d0d`).

> Note on path: the project layout uses `extraction/` (not `extractors/`
> as named in the task brief). Treated as the same directory.

---

## 1. Per-extractor inventory

### 1.1 `parser_extractor.py` — sv_parser layer

- **Path:** `src/kgweave/knowledge_graph/extraction/parser_extractor.py`
- **Input format:** SystemVerilog `.sv` / `.svh` source (parsed via the `sv-parser` Rust bridge — pre-elaboration syntactic AST)
- **`extractor_source`:** `"sv_parser"` (`parser_extractor.py:821, 834`)
- **`layer` tag on emissions:** *(none — not promoted to a `layer=` value; this is the implicit "sv_parser" layer per the demo's enumeration)*
- **Emitted Entity types:**
  - `RTL_Module` (`:352`)
  - `Package` (`:454`)
  - `Parameter` (`:486, :555`)
  - `Port` (with `port_direction`) (`:531, :589`)
  - `Signal` (`:611`)
  - `Instance` (`:658`)
  - `RTL_Module` (Instance's target type, `:672-673`)
  - `Generate` (`:700`)
  - `Task_Function` (`:721`)
- **Emitted Triple predicates:**
  - `contains` (`:489, :535, :557, :593, :613, :660, :702, :723`)
  - `instantiates` (`:664`)
  - `depends_on` (`:744`)
- **One-line summary:** Reads each .sv source file's pre-elaboration syntax tree and emits the structural skeleton: modules, packages, parameters, ports (with direction), signals, instances, generates, tasks/functions. Module-internal hierarchy via `contains`; cross-module via `instantiates` / `depends_on`.

### 1.2 `sv_connectivity.py` — slang layer

- **Path:** `src/kgweave/knowledge_graph/extraction/sv_connectivity.py`
- **Input format:** SystemVerilog source elaborated via pyslang (post-elaboration with parameter resolution, bind handling, generates expanded)
- **`extractor_source`:** `"slang"` (e.g. `:340, :407, :437`)
- **`layer` tags:**
  - `"slang"` on `data_flows` triples (`:734, :740, :746, :751, :760`)
  - `SV_CONNECTIVITY_SOURCE` (the literal string `"__sv_connectivity_batch__"` — `:61, :438, :457, :666`) on the auto-synthesized definition entities — **this is anomalous, see §4**.
  - Most other emissions are layer-unset → grouped under `"slang"` by the demo's layer-of-origin inference.
- **Emitted Entity types** (all with `extractor_source=["slang"]`):
  - `ClockDomain` (`:405`)
  - `ResetDomain` (`:412`)
  - `RTL_Module` (`:436, :455`) — also `"Interface"`, `"Program"` via `definition_kinds` dict (`:520, :522, :524`)
  - `Port` (auto-promoted entity with `port_direction`) (`:662`)
  - `SVA_Assertion` (`:1066`)
  - `FSM` (`:1415`)
  - `FSM_State` (`:1429`)
  - `Covergroup_SV` (`:2241`)
  - `Coverpoint` (`:2264`)
  - `Covergroup_SampleArg` (`:2330`)
  - `CoverBin` (`:2354`)
  - `CoverCross` (`:2372`)
- **Emitted Triple predicates** (all via the local `emit()` helper at `:325-346`):
  - `instance_of` (`:493`)
  - `part_of` (`:497`)
  - `instantiates` (`:501`)
  - `contains` (`:641`)
  - `drives` (`:708, :710, :712, :713, :716`) — legacy direction predicate; superseded by `data_flows` for port-net edges
  - `data_flows` (`:731-760`) — carries `attributes={"flow_kind": "port_in"|"port_out"}`
  - `binds_parameter` (`:796`)
  - `reset_by` (`:891`)
  - `clocked_by` (`:901`)
  - `has_assertion` (`:1074`)
  - `references_signal` (`:1144`) — assertion-signal cross-reference
  - `has_fsm` (`:1420`)
  - `has_state` (`:1434`)
  - `transitions_to` (`:1647`)
  - `reads` (`:1901, :1956`) — statement-level dataflow walker fallback inside connectivity (with `lhs_slice` / `rhs_slice` attributes)
  - `bound_into` (`:2130, :2146`) — bind-directive unresolved-target audit edge
  - `defined_in` (`:2247`)
  - `has_coverpoint` (`:2270`)
  - `observes` (`:2317, :2338`)
  - `has_sample_arg` (`:2336`)
  - `has_bin` (`:2360`)
  - `has_cross` (`:2378`)
  - `crosses` (`:2393`)
- **One-line summary:** The big one. Elaborates the design with pyslang, then walks the post-elab tree and emits structural + assertion + FSM + coverage + dataflow edges. This is the **primary candidate for replacement** by the `build_kg` pyslang experiment.

### 1.3 `sv_dataflow_extractor.py` — slang / sv_dataflow layer

- **Path:** `src/kgweave/knowledge_graph/extraction/sv_dataflow_extractor.py`
- **Input format:** pyslang-elaborated SV (per-process walker)
- **`extractor_source`:** `"sv_dataflow"` (`:62`)
- **`layer` tags:** `"sv_dataflow"` (`:360, :390, :483`); also `"slang"` on cross-module dataflow port edges (`:405`)
- **Emitted Entity types:**
  - `Process` (`:480`)
- **Emitted Triple predicates:**
  - `assigned_in` (`:356`)
  - `drives_signal` (`:386`)
  - `data_flows` (`:401`) — layer-tagged `"slang"`, parallel to sv_connectivity's port-net edges
- **One-line summary:** Walks each always/assign/initial process and emits the process node plus signal-write provenance (`assigned_in`, `drives_signal`).

### 1.4 `sv_dataflow_v2_statements.py` — ast layer (Track B)

- **Path:** `src/kgweave/knowledge_graph/extraction/sv_dataflow_v2_statements.py`
- **Input format:** pyslang-elaborated SV statement tree per process
- **`extractor_source`:** `SV_V2_STMT_SOURCE` (a module-level string constant)
- **`layer` tag:** `"ast"` (`SV_V2_STMT_LAYER` at `:405, :418`)
- **Emitted Entity types:**
  - `Condition` (`:430, :443`)
  - `IfStatement` (`:457`)
  - `Branch` (`:516, :549, :691`)
  - `CaseStatement` (`:597`)
  - `Loop` (`:742`)
  - `Assignment` (`:797`)
- **Emitted Triple predicates:**
  - `contains` (`:274` — parent_pred default)
  - `condition_of` (`:432`)
  - `then_branch` (`:461` arm_pred)
  - `elif_branch` (`:475` arm_pred)
  - `else_branch` (`:553`)
  - `selector` (`:608`)
  - `case_item` (`:695`)
  - `default_branch` (`:695`)
  - `case_value` (`:709`)
  - `body_of` (`:533, :558, :718, :752` parent_pred)
  - `lhs` (`:810`)
  - `rhs` (`:814`)
- **One-line summary:** Track-B statement walker — materialises if/else/case/loop/assignment structure with branch lineage. Produces the AST-layer skeleton that downstream `build_kg` would extend.

### 1.5 `sv_v2_walker.py` — ast layer (Track A: expression walker)

- **Path:** `src/kgweave/knowledge_graph/extraction/sv_v2_walker.py`
- **Input format:** pyslang expression sub-trees (operands of conditions / RHS / case-values etc.)
- **`extractor_source`:** `V2_WALKER_SOURCE`
- **`layer` tag:** `"ast"` (`_AST_LAYER` at `:50`)
- **Emitted Entity types:**
  - `Operator` (`:553`)
  - `Literal` (`:651`)
  - `Index` (`:702`)
- **Emitted Triple predicates:**
  - `operand` (`:580`, with `attributes["operand_index"]`)
  - `slice_of` (`:717`)
  - `slice_msb` (`:728`)
  - `slice_lsb` (`:730`)
- **One-line summary:** Decomposes expressions into Operator / Literal / Index trees with operand-indexed edges. Pure pyslang AST walker.

### 1.6 `sv_v2_integration.py` — ast layer (bridge)

- **Path:** `src/kgweave/knowledge_graph/extraction/sv_v2_integration.py`
- **Input format:** Already-emitted Track-A and Track-B entities (post-processor)
- **`extractor_source`:** `V2_INTEGRATION_SOURCE`
- **`layer` tag:** `"ast"` (`:232`)
- **Emitted Entity types:** *(none — bridge-only)*
- **Emitted Triple predicates:**
  - `operand` and pass-through predicate variable `bridge_pred` (`:217, :228`) — same predicate as the Track-B stub edge (`lhs`, `rhs`, `selector`, `case_value`) — re-targeted onto Track-A expression roots with `attributes={"bridge": True, "stub_pred": <orig>}`.
- **One-line summary:** Wires Track-B statement stubs to Track-A expression roots; emits zero new entities, only re-pointed edges.

### 1.7 `sv_xref_resolver.py` — ast layer

- **Path:** `src/kgweave/knowledge_graph/extraction/sv_xref_resolver.py`
- **Input format:** pyslang elaborated identifier expressions (Track C)
- **`extractor_source`:** `XREF_SOURCE = "sv_xref_resolver"` (`:77`)
- **`layer` tag:** `"ast"` (`:256, :269`)
- **Emitted Entity types:** *(none)*
- **Emitted Triple predicates:**
  - `references` (`:249, :262`) — resolved + unresolved sentinel variants with `confidence_tier` + `resolved` flags
- **One-line summary:** Cross-references identifier uses to declared Signal/Port entities. Pure pyslang.

### 1.8 `hjson_csr_extractor.py` — hjson_csr layer

- **Path:** `src/kgweave/knowledge_graph/extraction/hjson_csr_extractor.py`
- **Input format:** OpenTitan `*.hjson` CSR description files
- **`extractor_source`:** `HJSON_CSR_SOURCE = "hjson_csr"` (`:52`)
- **`layer` tag:** *(none set explicitly; demo bins under `"hjson_csr"`)*
- **Emitted Entity types:**
  - `RTL_Module` (`:109`) — the CSR-block's parent module name
  - `CSR_Register` (`:128`)
  - `CSR_Field` (`:161`)
- **Emitted Triple predicates:**
  - `has_register` (`:139`)
  - `has_field` (`:169`)
- **One-line summary:** Parses hjson CSR specs and emits Register/Field hierarchy under the named RTL module.

### 1.9 `ipxact_extractor.py` — ipxact layer

- **Path:** `src/kgweave/knowledge_graph/extraction/ipxact_extractor.py`
- **Input format:** IP-XACT XML component / bus-definition descriptions
- **`extractor_source`:** `IPXACT_SOURCE = "ipxact"` (`:86`)
- **`layer` tag:** `"ipxact"` (set on every emission)
- **Emitted Entity types:** `IPXACT_Component`, `IPXACT_Port`, `IPXACT_Clock`, `IPXACT_Reset`, `IPXACT_Register`, `IPXACT_Field`, `IPXACT_BusInterface`, `IPXACT_AddressBlock`, `IPXACT_FieldEnum`, `IPXACT_Parameter`, `IPXACT_FileSet`, `IPXACT_BusType`, `IPXACT_LogicalPort`, `IPXACT_MemoryMap`, `IPXACT_AddressSpace`
- **Emitted Triple predicates:** `aggregates_port`, `conforms_to`, `connects_to_address_space`, `contains_address_block`, `contains_register`, `exposes_memory_map`, `has_address_block`, `has_bus_interface`, `has_ipxact_enum`, `has_ipxact_field`, `has_ipxact_fileset`, `has_ipxact_parameter`, `has_ipxact_port`, `has_ipxact_register`, `has_logical_port`, `has_memory_map`, `implemented_by`, `parameterizes`, `physical_for`, `specifies`
- **One-line summary:** Pure XML reader; produces the entire IPXACT projection of component metadata, untouched by anything SV.

### 1.10 `sdc_extractor.py` — sdc layer

- **Path:** `src/kgweave/knowledge_graph/extraction/sdc_extractor.py`
- **Input format:** SDC / Synopsys TCL constraint files
- **`extractor_source`:** `SDC_SOURCE = "sdc"` (`:70`)
- **`layer` tag:** *(none explicit; demo bins as `"sdc"`)*
- **Emitted Entity types:** `ClockConstraint` (`:540`), `IODelay` (`:616`), `FalsePath` (`:656`), `MulticyclePath` (`:710`), `ClockGroup` (`:756`)
- **Emitted Triple predicates:**
  - `constrains_clock` (`:552`)
  - `relative_to_clock` (`:564, :635`)
  - `constrains_port` (`:626`)
  - `from_endpoint` (`:664, :719`)
  - `to_endpoint` (`:670, :725`)
  - `groups_clock` (`:766`)
- **One-line summary:** Parses TCL SDC; pure non-SV reader.

### 1.11 `markdown_doc_extractor.py` — markdown_doc layer

- **Path:** `src/kgweave/knowledge_graph/extraction/markdown_doc_extractor.py`
- **Input format:** Markdown documentation
- **`extractor_source`:** `MARKDOWN_DOC_SOURCE = "markdown_doc"` (`:51`)
- **`layer` tag:** *(none explicit; binned as `"markdown_doc"`)*
- **Emitted Entity types:**
  - `Section` (`:285`)
  - `entity_type` variable (`:438`) defaulting to `RTL_Module` — surfaces any already-known SV entity name found in prose, retyped to its known type (or `RTL_Module` fallback)
- **Emitted Triple predicates:**
  - `references` (`:330`) — Section→Section
  - `mentions` (`:452`) — Section→KnownEntity
- **One-line summary:** Section structure of MD docs plus prose mentions of known SV/IPXACT entities.

### 1.12 `spec_claim_extractor.py` — llm_doc layer

- **Path:** `src/kgweave/knowledge_graph/extraction/spec_claim_extractor.py`
- **Input format:** Markdown spec docs (with LLM-extracted YAML-front-matter or JSON claim payloads)
- **`extractor_source`:** `LLM_DOC_SOURCE = "llm_doc"` (`:42`)
- **`layer` tag:** `"llm_doc"` (`:503, :513, :524, :544`)
- **Emitted Entity types:**
  - `Section` (`:385`)
  - One of `VALID_CLAIM_TYPES` (`:47-52`): `StructuralClaim`, `BehavioralClaim`, `ProtocolClaim`, `SecurityClaim` (`:499`)
- **Emitted Triple predicates:**
  - `claims_about` (`:508`)
  - `target_entity` (`:519`)
  - `decomposes_into` (`:539`)
- **One-line summary:** LLM-mediated extraction of spec claims from prose; emits typed claim nodes anchored to sections and target SV/IPXACT entities.

### 1.13 `testplan_extractor.py` — testplan layer

- **Path:** `src/kgweave/knowledge_graph/extraction/testplan_extractor.py`
- **Input format:** lowRISC dvsim testplan hjson
- **`extractor_source`:** `TESTPLAN_SOURCE = "testplan"` (`:44`)
- **`layer` tag:** `"testplan"` (e.g. `:363, :383, :399, :420, :475, :600`)
- **Emitted Entity types:** `Testpoint` (`:340`), `Stage` (`:351`), `DVTest` (`:408`), `Covergroup` (`:445`)
- **Emitted Triple predicates:** `has_stage` (`:358`), `covers` (`:378, :394`), `tests` (`:415`), `collected_in` (`:470`), `mentions` (`:595`)
- **One-line summary:** Reads hjson testplans, builds Testpoint/Stage/DVTest/Covergroup hierarchy and ties testpoints to SV entities they cover.

### 1.14 `dv_test_realization_extractor.py` — dv_test_realization layer

- **Path:** `src/kgweave/knowledge_graph/extraction/dv_test_realization_extractor.py`
- **Input format:** UVM SV test class definitions (mapping DVTest names → realising .sv files)
- **`extractor_source`:** `DV_TEST_REALIZATION_SOURCE = "dv_test_realization"` (`:36`)
- **`layer` tag:** `"dv_test_realization"` (`:176`)
- **Emitted Entity types:** `SV_File` (`:163`)
- **Emitted Triple predicates:** `realized_by` (`:171`)
- **One-line summary:** Discovers which .sv file realises each testplan DVTest; emits the linking edge only.

### 1.15 `cpp_extractor.py` — cpp_ref_model + dpi_boundary layers

- **Path:** `src/kgweave/knowledge_graph/extraction/cpp_extractor.py`
- **Input format:** C / C++ ref-model and DPI-SV `.c/.cpp/.h` source
- **`extractor_source`:** `CPP_REF_MODEL_SOURCE = "cpp_ref_model"` (`:66`); `DPI_BOUNDARY_SOURCE = "dpi_boundary"` (`:67`)
- **`layer` tags:** `"cpp_ref_model"` and `"dpi_boundary"`
- **Emitted Entity types:** `CFile` (`:276`), `CFunction` (`:303`), `DPIBoundary` (`:531, :567`), and a generic `entity_type` variable (`:543`) for DPI-imported SV-side functions
- **Emitted Triple predicates:** `includes` (`:292`), `defined_in` (`:310`), `implements_dpi` (`:320`), `imports_dpi` (`:552`)
- **One-line summary:** Parses C/C++ ref-models and DPI boundaries; emits file/function/DPI-boundary graph.

### 1.16 `sw_test_extractor.py` — sw_test layer

- **Path:** `src/kgweave/knowledge_graph/extraction/sw_test_extractor.py`
- **Input format:** SW (firmware) C test files
- **`extractor_source`:** `SW_TEST_SOURCE = "sw_test"` (`:60`)
- **`layer` tag:** `"sw_test"` (`:571, :585, :654, :674, :690, :730`)
- **Emitted Entity types:** `SW_Test` (`:568, :582`)
- **Emitted Triple predicates:** `tests_module` (`:646, :669, :685`), `accesses_csr` (`:725`)
- **One-line summary:** Surfaces SW test files and their RTL-module / CSR coverage.

### 1.17 `uvm_sample_extractor.py` — uvm_sample layer

- **Path:** `src/kgweave/knowledge_graph/extraction/uvm_sample_extractor.py`
- **Input format:** UVM `.sv` testbench source — focused on covergroup sample callsites
- **`extractor_source`:** `UVM_SAMPLE_SOURCE = "uvm_sample"` (`:47`)
- **`layer` tag:** `"uvm_sample"` (set on every emission)
- **Emitted Entity types:** `UVMSampleWrapper` (`:441`), `UVMSampleCallsite` (`:504`), `SV_File` (`:542`), `UVMSampleArgExpr` (`:564`)
- **Emitted Triple predicates:** `wraps_covergroup` (`:448`), `samples_covergroup` (`:517`), `defined_in_uvm_file` (`:530`), `via_wrapper` (`:551`), `passes_arg` (`:572`), `binds_to_arg` (`:592`)
- **One-line summary:** UVM-side covergroup sampling audit — wrapper functions, callsites, the SV file they're in, and the arg expressions passed in.

### 1.18 `regex_extractor.py`

- **Path:** `src/kgweave/knowledge_graph/extraction/regex_extractor.py`
- **Input format:** Arbitrary natural-language text (markdown / prose docs)
- **`extractor_source`:** `"regex"` (`:126`)
- **`layer` tag:** *(none; un-binned, would land in default bucket)*
- **Emitted Entity types:** dynamic via `classify_type()` (`:383-421`) → `"technology"`, `"acronym"`, or the configurable `fallback_type` (default `"concept"`, `:139`)
- **Emitted Triple predicates:** `subset_of` (`:311`), `is_a` (`:328, :374`), `used_for` (`:342`), `uses` (`:358`)
- **One-line summary:** Generic CamelCase / acronym name-spotter with heuristic relation predicates. Not anchored to SV — feeds the legacy ontology layer.

### 1.19 `gliner_extractor.py`

- **Path:** `src/kgweave/knowledge_graph/extraction/gliner_extractor.py`
- **Input format:** Natural-language prose (GLiNER NER model)
- **`extractor_source`:** `"gliner"` (constructor identifier)
- **`layer` tag:** *(none)*
- **Emitted Entity types:** `"unknown"` (`:259`) — type resolution is a downstream concern
- **Emitted Triple predicates:** *(none directly emitted — passes through `t.predicate` from upstream relation candidates, `:285`)*
- **One-line summary:** Neural NER over prose. Adds candidate entity names; predicates come from co-running extractors.

### 1.20 `llm_extractor.py`

- **Path:** `src/kgweave/knowledge_graph/extraction/llm_extractor.py`
- **Input format:** Prose / chunked docs sent to an LLM
- **`extractor_source`:** the configured `self.extractor_name` (`:426, :466`)
- **`layer` tag:** *(none)*
- **Emitted Entity types:** anything in `self._valid_node_types` (schema-validated, fallback when unknown) — `entity_type` is read from the LLM JSON, validated against schema (`:410-415, :424`)
- **Emitted Triple predicates:** any predicate in `self._valid_edge_types` (`:453, :462`) — schema-validated relation string from LLM JSON
- **One-line summary:** Schema-bounded LLM extraction; emits whatever the configured schema permits. Variable surface — not a fixed predicate set.

### 1.21 `python_parser.py`

- **Path:** `src/kgweave/knowledge_graph/extraction/python_parser.py`
- **Input format:** Python `.py` source (AST module)
- **Emitted Entity types:** `PythonImport` (`:97, :119`), `PythonClass` (`:195`), `PythonFunction`, `PythonVariable` (per top-level grep)
- **Emitted Triple predicates:** `depends_on` (`:106, :128, :218`), `contains` (`:204`)
- **One-line summary:** Python-source structural walker. Unused for SV/HW flow.

### 1.22 `bash_parser.py`

- **Path:** `src/kgweave/knowledge_graph/extraction/bash_parser.py`
- **Input format:** Bash `.sh` source
- **Emitted Entity types:** `BashFunction` (`:259`), `BashScript` (`:281`), `BashVariable` (`:301, :321`)
- **Emitted Triple predicates:** `contains` (`:266, :308, :328`), `depends_on` (`:288`)
- **One-line summary:** Bash-source walker. Auxiliary; not exercised by the OpenTitan demo.

### 1.23 `buildsys_*.py` — build-system readers

- **Paths:** `buildsys_bazel.py`, `buildsys_dvsim.py`, `buildsys_fusesoc.py`, `buildsys_makefile.py`, `buildsys_uvm_testlist.py`
- **Input format:** BUILD.bazel, dvsim `sim_cfg.hjson`, FuseSoC `.core`, GNU Makefiles, UVM testlists
- **Emit shape:** **Not Entity/Triple.** They produce `BuildSystemLink` records (from `kgweave.knowledge_graph.common.sw_test_buildsys`) consumed by `sw_test_extractor` / `dv_test_realization_extractor` to associate tests with the IP they exercise.
- **One-line summary:** Pure config readers; contribute indirectly via downstream sw_test / dv_test_realization emitters.

### 1.24 `testplan_normalizer.py`

- **Path:** `src/kgweave/knowledge_graph/extraction/testplan_normalizer.py`
- **Input format:** Already-emitted Testpoint/DVTest/Covergroup entities + sibling lists
- **Emit shape:** No direct Entity/Triple construction; canonicalises names / merges duplicates for `testplan_extractor`.

### 1.25 `base.py`, `__init__.py`

- Pure framework / protocol scaffolding. No emissions.

---

## 2. Classification table

| Entity Type | Predicates Involving | Source Extractor(s) | Layer | Classification | Notes |
|---|---|---|---|---|---|
| `RTL_Module` | `contains` (subj), `instantiates` (subj/obj), `instance_of` (obj), `part_of`, `depends_on`, `has_assertion`, `has_fsm`, `reset_by`, `clocked_by`, `bound_into`, `defined_in` (obj), `tests_module` (obj), `has_register` (subj), `mentions` (obj), `realized_by` (subj), `references` (obj) | parser_extractor, sv_connectivity, hjson_csr_extractor, markdown_doc_extractor, dv_test_realization, sw_test, sv_v2_walker (indirect via signal qualified names), sv_xref_resolver | sv_parser / slang / hjson_csr / markdown_doc / dv_test_realization / sw_test | **mixed** | Emitted natively by parser_extractor + sv_connectivity (sv-ast). Also synthesized by hjson_csr_extractor as parent of CSR registers (non-sv) and used as the fallback type when markdown_doc_extractor recognises an entity name in prose (non-sv). |
| `Interface`, `Program` | `instantiates`, `contains` | sv_connectivity (`:520, :522`) | slang | **sv-ast** | Variant of RTL_Module via `definition_kinds` lookup. |
| `Package` | `contains`, `depends_on` | parser_extractor (`:454`) | sv_parser | **sv-ast** | |
| `Parameter` | `contains` (obj), `binds_parameter` (obj) | parser_extractor (`:486, :555`), sv_connectivity (`:796`) | sv_parser / slang | **sv-ast** | |
| `Port` | `contains`, `drives`, `data_flows`, `binds_parameter` (rare) | parser_extractor (`:531, :589`), sv_connectivity (`:662`) | sv_parser / slang | **sv-ast** | Carries `port_direction` attribute. |
| `Signal` | `contains`, `references_signal` (obj), `reads` (subj/obj), `assigned_in` (subj), `drives_signal`, `data_flows`, `references` (obj) | parser_extractor (`:611`), sv_dataflow_extractor, sv_xref_resolver | sv_parser / sv_dataflow / ast | **sv-ast** | |
| `Instance` | `contains` | parser_extractor (`:658`) | sv_parser | **sv-ast** | |
| `Generate` | `contains` | parser_extractor (`:700`) | sv_parser | **sv-ast** | |
| `Task_Function` | `contains` | parser_extractor (`:721`) | sv_parser | **sv-ast** | |
| `ClockDomain` | `clocked_by` (obj) | sv_connectivity (`:405`) | slang | **sv-ast** | |
| `ResetDomain` | `reset_by` (obj) | sv_connectivity (`:412`) | slang | **sv-ast** | |
| `SVA_Assertion` | `has_assertion` (obj), `references_signal` (subj) | sv_connectivity (`:1066`) | slang | **mixed** | Body comes from SV AST; some assertions originate in spec comments. The whitelist groups this with structural types but spec-anchored SVA could come via spec_claim too — currently doesn't, but the demo's classification has it as structural. |
| `FSM` | `has_fsm` (obj), `has_state` (subj) | sv_connectivity (`:1415`) | slang | **sv-ast** | |
| `FSM_State` | `has_state` (obj), `transitions_to` (subj/obj) | sv_connectivity (`:1429`) | slang | **sv-ast** | |
| `Process` | `assigned_in` (obj), `drives_signal` (subj) | sv_dataflow_extractor (`:480`) | sv_dataflow | **sv-ast** | NOT in demo's `structural_types` whitelist — see §4. |
| `Covergroup_SV` | `defined_in`, `has_coverpoint`, `has_sample_arg`, `wraps_covergroup` (obj), `samples_covergroup` (obj) | sv_connectivity (`:2241`), uvm_sample_extractor | slang / uvm_sample | **sv-ast** | The structural body is SV; UVM-side callsite is a separate-file extractor (mixed). |
| `Coverpoint` | `has_coverpoint`, `observes`, `has_bin` | sv_connectivity (`:2264`) | slang | **sv-ast** | |
| `CoverBin` | `has_bin` (obj) | sv_connectivity (`:2354`) | slang | **sv-ast** | |
| `CoverCross` | `has_cross`, `crosses` | sv_connectivity (`:2372`) | slang | **sv-ast** | |
| `Covergroup_SampleArg` | `has_sample_arg` (obj) | sv_connectivity (`:2330`) | slang | **sv-ast** | |
| `Condition`, `IfStatement`, `Branch`, `CaseStatement`, `Loop`, `Assignment` | `condition_of`, `then_branch`, `elif_branch`, `else_branch`, `selector`, `case_item`, `default_branch`, `case_value`, `body_of`, `lhs`, `rhs`, `contains` | sv_dataflow_v2_statements | ast | **sv-ast** | Track-B statement skeleton. Pure pyslang. |
| `Operator`, `Literal`, `Index` | `operand`, `slice_of`, `slice_msb`, `slice_lsb` | sv_v2_walker | ast | **sv-ast** | Track-A expression skeleton. Pure pyslang. |
| `CSR_Register` | `has_register` (obj), `has_field` (subj), `accesses_csr` (obj) | hjson_csr_extractor (`:128`), sw_test (obj of accesses_csr) | hjson_csr / sw_test | **mixed** | Names also surface in .sv as parameters/regfile literals (could be reified by build_kg), but the *semantic* metadata (offset, access mode, reset value) only exists in the hjson spec — non-sv. |
| `CSR_Field` | `has_field` (obj) | hjson_csr_extractor (`:161`) | hjson_csr | **non-sv** | |
| `Section` | `references`, `mentions`, `claims_about` | markdown_doc_extractor, spec_claim_extractor | markdown_doc / llm_doc | **non-sv** | |
| `StructuralClaim`, `BehavioralClaim`, `ProtocolClaim`, `SecurityClaim` | `claims_about` (obj), `target_entity`, `decomposes_into` | spec_claim_extractor | llm_doc | **non-sv** | Spec-prose origin only; build_kg cannot reach this. |
| `ClockConstraint`, `IODelay`, `FalsePath`, `MulticyclePath`, `ClockGroup` | `constrains_clock`, `constrains_port`, `relative_to_clock`, `from_endpoint`, `to_endpoint`, `groups_clock` | sdc_extractor | sdc | **non-sv** | SDC TCL is not SV. |
| `IPXACT_*` (15 types) | 20 `*_ipxact_*` predicates + structural | ipxact_extractor | ipxact | **non-sv** | IP-XACT XML only. |
| `Testpoint` | `has_stage`, `covers`, `tests`, `mentions` | testplan_extractor | testplan | **non-sv** | |
| `Stage` | `has_stage` (obj) | testplan_extractor | testplan | **non-sv** | |
| `DVTest` | `tests`, `realized_by` (subj) | testplan_extractor, dv_test_realization | testplan / dv_test_realization | **non-sv** | |
| `Covergroup` | `collected_in`, `covers` (obj) | testplan_extractor | testplan | **mixed** | Distinct from `Covergroup_SV`! See §4 (naming collision). |
| `SV_File` | `realized_by` (obj), `defined_in_uvm_file` (obj) | dv_test_realization, uvm_sample_extractor | dv_test_realization / uvm_sample | **mixed** | SV-source-anchored but the *enumeration* of files comes from non-SV (testplan + UVM file walk). |
| `CFile` | `includes`, `defined_in` (obj of) | cpp_extractor | cpp_ref_model | **non-sv** | |
| `CFunction` | `defined_in`, `implements_dpi`, `imports_dpi` | cpp_extractor | cpp_ref_model | **non-sv** | |
| `DPIBoundary` | `implements_dpi` (obj), `imports_dpi` (obj) | cpp_extractor | dpi_boundary | **mixed** | Boundary spans C-side (cpp_extractor) and SV-side (could be lifted by build_kg as DPI import declarations). |
| `SW_Test` | `tests_module`, `accesses_csr` | sw_test_extractor | sw_test | **non-sv** | |
| `UVMSampleWrapper`, `UVMSampleCallsite`, `UVMSampleArgExpr` | `wraps_covergroup`, `samples_covergroup`, `defined_in_uvm_file`, `via_wrapper`, `passes_arg`, `binds_to_arg` | uvm_sample_extractor | uvm_sample | **mixed** | Reads .sv source (UVM is SV), but with a regex/scan approach focused on `.sample()` callsites. In principle build_kg's pyslang elaboration could reach these (UVM compiles), but in practice these are pre-elaboration audit signals on tb-only sources. |
| `BashFunction`, `BashScript`, `BashVariable` | `contains`, `depends_on` | bash_parser | (unbinned) | **non-sv** | Outside RTL flow. |
| `PythonClass`, `PythonFunction`, `PythonImport`, `PythonVariable` | `contains`, `depends_on` | python_parser | (unbinned) | **non-sv** | |
| `technology`, `acronym`, `concept` (fallback), `unknown`, dynamic LLM types | `is_a`, `subset_of`, `used_for`, `uses` + LLM-schema preds | regex_extractor, gliner_extractor, llm_extractor | (unbinned) | **non-sv** | Generic prose-text typing. Not consumed by structural views. |

---

## 3. Migration impact

### 3.1 Becomes redundant if `build_kg` covers all predicates

These are pure pyslang-AST emitters; if the new `build_kg` S-rule set
covers their predicate surface they can be retired:

- **`sv_connectivity.py`** — biggest prize. ~30 predicates including all
  hierarchy (`instantiates`, `part_of`, `instance_of`, `contains`),
  port-net dataflow (`drives`, `data_flows`), parameter binding
  (`binds_parameter`), clock/reset attribution (`clocked_by`,
  `reset_by`), assertions (`has_assertion`, `references_signal`),
  FSMs (`has_fsm`, `has_state`, `transitions_to`), coverage
  (`defined_in`, `has_coverpoint`, `observes`, `has_sample_arg`,
  `has_bin`, `has_cross`, `crosses`), bind directives (`bound_into`),
  statement-level reads (`reads` with `lhs_slice`/`rhs_slice`).
- **`sv_dataflow_extractor.py`** — `Process` entity + `assigned_in`,
  `drives_signal`, `data_flows`. All from pyslang.
- **`sv_dataflow_v2_statements.py`** (Track B) — already pyslang-driven;
  the new build_kg path likely subsumes it directly.
- **`sv_v2_walker.py`** (Track A) — pyslang expression walker. Same.
- **`sv_v2_integration.py`** — bridge only; subsumed when Track A+B are.
- **`sv_xref_resolver.py`** (Track C) — `references` predicate from
  pyslang identifier expressions.
- **`parser_extractor.py`** — partial overlap (see §3.3). Pure
  syntactic structural skeleton via sv-parser; everything except
  unelaborated parse-only sources is also reachable from pyslang
  (which sv_connectivity already proves by emitting `RTL_Module`
  fallback entities for un-elaborated bodies at `:452-458`).

### 3.2 Independent of build_kg — stays as-is

- `hjson_csr_extractor.py` — hjson input format.
- `ipxact_extractor.py` — XML input format.
- `sdc_extractor.py` — TCL input format.
- `markdown_doc_extractor.py` — Markdown input format.
- `spec_claim_extractor.py` — LLM over Markdown spec docs.
- `testplan_extractor.py` — hjson input format.
- `dv_test_realization_extractor.py` — hjson cross-reference into SV.
  (The SV-side leg is a filename match, not an AST walk.)
- `cpp_extractor.py` — C/C++ input format. (build_kg sees SV-side DPI
  imports only, not the C bodies.)
- `sw_test_extractor.py` — C firmware input.
- `buildsys_*.py` — build-system config readers; emit BuildSystemLink
  not Entity/Triple.
- `regex_extractor.py`, `gliner_extractor.py`, `llm_extractor.py` —
  prose-text extractors. Different input modality entirely.
- `python_parser.py`, `bash_parser.py` — non-RTL languages.

### 3.3 Partial overlap

- **`parser_extractor.py`**: Emits the same RTL skeleton that
  pyslang elaboration produces, but from the **pre-elaboration** sv-parser
  syntax tree. This matters in two corners:
  1. **Sources that fail to elaborate** (missing dependencies, unbound
     params) — sv-parser still surfaces their module/port/signal skeleton.
     `build_kg` will not.
  2. **`depends_on` predicate** (`:744`) — package-level `import pkg::*`
     edges. Pyslang-elaborated modules transparently absorb package items
     so the `depends_on` link is harder to surface from a slang walk
     unless the S-rules explicitly track `PackageImportItem`.
  Migration verdict: build_kg subsumes the common path; keep
  parser_extractor for fallback-on-elab-failure and `depends_on`.

- **`uvm_sample_extractor.py`**: Reads `.sv` (so technically a sv-source
  consumer) but produces audit-style entities (`UVMSampleCallsite`,
  `UVMSampleWrapper`, etc.) that are specifically about UVM testbench
  *callsite* facts the structural view doesn't otherwise carry. If
  build_kg elaborates the UVM tb, the S-rule set can in principle
  extract these — but it's a TB-only signal and the migration plan
  should treat it as "could be subsumed, low priority". The
  `via_wrapper`/`passes_arg`/`binds_to_arg` predicates depend on
  ConcatenationExpression / IdentifierName decomposition of the
  `sample()` argument list and would require dedicated S-rules.

- **`sv_connectivity.py`'s SVA emission**: Most SVA assertions in
  OpenTitan come from `.sv` source, so they're sv-ast. But some are
  authored in spec docs and only become assertions through manual
  translation. The `SVA_Assertion` entity is therefore *currently*
  sv-ast-only (no spec_claim_extractor cross-link exists), but the
  inventory should note that **spec→SVA traceability is a known gap**
  that the migration could close by linking `BehavioralClaim` →
  `SVA_Assertion` via shared `target_entity` / signal references.

---

## 4. Gaps / interesting findings

### 4.1 Entity types EMITTED but NOT in `structural_types` whitelist

The demo's `structural_types` list (`scripts/demo_opentitan_aes.py:860-880`) governs the HTML export view. Types emitted by extractors but **missing** from that list (so they're invisible in the structural view):

- **`Process`** — emitted by `sv_dataflow_extractor.py:480`. High-value behavioural node, hidden.
- **`Interface`, `Program`** — emitted by `sv_connectivity.py:520, 522` via `definition_kinds`. Treated as `RTL_Module` siblings but with distinct types; only `RTL_Module` is whitelisted.
- **`Package`, `Signal`, `Instance`, `Generate`, `Task_Function`** — emitted by `parser_extractor.py` but only `Instance` and `Port` survive into the whitelist; `Package`/`Signal`/`Generate`/`Task_Function` are dropped from the structural view.
- **Track-B statement types** — `Condition`, `IfStatement`, `Branch`, `CaseStatement`, `Loop`, `Assignment` — and **Track-A expression types** — `Operator`, `Literal`, `Index`. By design these are hidden from the default structural view (the demo notes at `:902-906` that the AST layer is suppressed unless `include_layers={"slang","ast"}` is passed), but the migration audit should note them.
- **`Covergroup` vs `Covergroup_SV`** — both whitelisted, but they are *different concepts* (testplan-declared vs RTL-declared) — see 4.3.

**Risk for migration:** if build_kg replaces sv_connectivity, it must continue to *type* unelaborated `instantiates`-target nodes as `RTL_Module` (currently done at `sv_connectivity.py:452-458`) or `RTL_Module`-typed queries silently lose nodes.

### 4.2 Predicate-name variance / synonyms

- **`drives` vs `data_flows`** (`sv_connectivity.py:708-716` vs `:731-760`). Both are emitted for port-net edges. `drives` is the legacy predicate, `data_flows` is the v2 schema name (with `flow_kind` attribute). Migration must pick one or emit both — currently both are emitted, which doubles the edge count. **Action:** audit consumers; if RagWeave still reads `drives`, plan a deprecation; otherwise drop in build_kg.
- **`data_flows` is also emitted by `sv_dataflow_extractor.py:401`** with `layer="slang"` — overlaps with sv_connectivity's emission. Likely redundant; pick one source-of-truth.
- **`defined_in`** is overloaded: used by `cpp_extractor.py:310` (CFunction → CFile), `sv_connectivity.py:2247` (Covergroup_SV → RTL_Module), `uvm_sample_extractor.py:530` (callsite → uvm file via predicate `defined_in_uvm_file`). Same word, three semantically distinct edges. Not a bug, but consumers must filter by `extractor_source`/`layer` for unambiguity.
- **`contains`** is the workhorse predicate — emitted by `parser_extractor` (module→port/signal/param/inst/gen/task), `sv_connectivity` (module→instance), `sv_dataflow_v2_statements` (process→if/case/loop), `python_parser`, `bash_parser`. Migration must preserve the exact subject/object types each consumer expects.
- **`references`** is used by `markdown_doc_extractor.py:330` (Section→Section) **and** `sv_xref_resolver.py:249, 262` (expression→Signal/Port). Disjoint subject/object types so they don't actually collide, but it's a foot-gun.

### 4.3 Naming collisions across layers

- **`Covergroup` (testplan)** vs **`Covergroup_SV` (slang)** — *different entity types* representing the same OpenTitan concept from two angles. They are NOT linked by any predicate in the current emission set; this is a structural gap. The migration is a good moment to either alias them or add a `defined_in_testplan` / `realized_by_sv` cross-edge.
- **`SV_File`** is emitted by both `dv_test_realization_extractor` and `uvm_sample_extractor`, with no de-dup contract between them. If a UVM TB file realises a DVTest, two `SV_File` entities share the same name — the backend's name-keyed dedup will merge them, but their `extractor_source` lists won't.

### 4.4 Layer-tag anomalies

- **`sv_connectivity.py` uses `SV_CONNECTIVITY_SOURCE = "__sv_connectivity_batch__"` as the `layer=` value** for fallback definition entities (`:438, :457, :666`). That is **not** a real layer name; it leaks an internal batching token into the layer field. The demo's per-layer summary loop (`scripts/demo_opentitan_aes.py:883-900`) will not bin these entities under `"slang"`. **Highest-priority finding** for migration: build_kg must use `layer="slang"` (or whatever the new layer name is), not the batch token.
- Most sv-AST extractors (`parser_extractor`, `hjson_csr_extractor`, `sdc_extractor`, `markdown_doc_extractor`) **do not set `layer=` explicitly** on their emissions. The layer binning relies on the backend inferring layer from `extractor_source`. This is fragile — if extractor_source is renamed during the migration, layer telemetry breaks silently.

### 4.5 Dead / sparse paths

- `python_parser.py` and `bash_parser.py` exist but are not invoked by the OpenTitan demo. They're plugged into the registry but never produce structural-type emissions for the RTL workflow.
- `regex_extractor.py`'s `subset_of`, `used_for`, `uses`, `is_a` predicates and `technology` / `acronym` / `concept` types are nowhere in the structural whitelist, the layer enumeration, or any consumer's edge-type schema (validated only against the legacy `SchemaDefinition`). Effectively legacy / shadow output.
- `gliner_extractor.py` only emits `type="unknown"` — a deliberate stub; downstream type resolution never happens for it in the demo path.
- `llm_extractor.py` emits *any* schema-permitted predicate — surface is dynamic. The migration cannot rely on a fixed predicate list for this extractor; build_kg neither subsumes it nor needs to.

### 4.6 Missing build_kg targets surfaced during this audit

Things build_kg's S-rule set will need to cover to achieve zero-loss migration of sv_connectivity:

1. The `reads` predicate with `lhs_slice` / `rhs_slice` attributes for sliced reads (`sv_connectivity.py:1901-1908`).
2. The `bound_into` audit edge for unresolved bind directives (`:2130-2151`) — pyslang silently drops these from elaboration, so build_kg must walk bind directives explicitly.
3. The `port_direction` attribute on Port entities — preserved through entity dedup (`port_entities` dict at `:323`).
4. `flow_kind` attribute on `data_flows` triples (`port_in`/`port_out`/inout duplication).
5. The fallback typing of `instantiates`-target nodes as `RTL_Module` for un-elaborated bodies (`:452-458`).
6. Cover-cross→coverpoint resolution (`crosses` edge at `:2393` requires symbol-table lookup on the cross's `iffExpr` / `bins`).

### 4.7 Recency context

```
6bb8d0d iter-016: lift regex_extractor.py natural-language prose patterns to noqa permitted zone
7a02c12 iter-015: replace re.sub header-strip in gliner_extractor + rename fragile name var in sv_v2_walker
e52a299 iter-014: replace 4 regex hits in testplan_extractor with structural char scanners
1e8e237 iter-013: replace _re.findall+_IDENT_RE in sv_connectivity assertion-signal extraction with spec.clocking+syntax.visit(TokenKind.Identifier)
2cf04a3 iter-012: annotate structural Make-grammar checks in buildsys_makefile with noqa markers
```

Active churn on `regex_extractor`, `gliner_extractor`, `sv_connectivity`, `testplan_extractor`, and `buildsys_makefile` over the last week — the auto-research regex-fragility branch is hardening these modules against AST-fragility. None of the iter commits change the emission surface; safe to use this inventory as the migration baseline.
