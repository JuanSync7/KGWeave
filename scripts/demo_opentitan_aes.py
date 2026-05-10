"""Build a KG from OpenTitan AES RTL and export an interactive HTML graph.

Walks ~/RagWeave/opentitan_data/hw/ip/aes/rtl, runs the pyslang-backed
SVParserExtractor on every .sv file, attempts a slang elaboration as a
best-effort second pass, then exports to HTML.

Usage:
    uv run python scripts/demo_opentitan_aes.py
"""

from __future__ import annotations

import os
from pathlib import Path

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.types import (
    KGConfig,
    ProjectConventions,
    load_schema,
)
from kgweave.knowledge_graph.community import CommunityDetector
from kgweave.knowledge_graph.export.sigma_export import export_html
from kgweave.knowledge_graph.extraction import (
    CppRefModelExtractor,
    DVTestRealizationExtractor,
    HJSONCSRExtractor,
    IPXACTExtractor,
    MarkdownDocExtractor,
    SDCExtractor,
    SlangHierarchyAnalyzer,
    SVParserExtractor,
    SWTestExtractor,
    TestplanExtractor,
    UVMSampleExtractor,
    build_dpi_boundary_entities,
    extract_dpi_boundaries_with_scope,
)


REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "config" / "kg_schema.yaml"
SV_STUBS_DIR = REPO / "data" / "sv_stubs"

OT_ROOT = Path(os.environ.get(
    "KGWEAVE_OPENTITAN_ROOT",
    str(Path.home() / "RagWeave" / "opentitan_data"),
))
AES_ROOT = OT_ROOT / "hw" / "ip" / "aes"
RTL_DIR = AES_ROOT / "rtl"
BIND_SVA_DIR = AES_ROOT / "dv" / "sva"
COV_DIR = AES_ROOT / "dv" / "cov"
DV_UTILS_INC_DIR = OT_ROOT / "hw" / "dv" / "sv" / "dv_utils"
DOC_DIR = AES_ROOT / "doc"
HJSON_PATH = AES_ROOT / "data" / "aes.hjson"

OUT_DIR = REPO / "data" / "demo"
OUT_HTML = OUT_DIR / "opentitan_aes.html"
FILELIST = OUT_DIR / "opentitan_aes.f"
SDC_PATH = OUT_DIR / "aes_synthetic.sdc"
IPXACT_PATH = OUT_DIR / "aes_synthetic.ipxact.xml"
TESTPLAN_PATHS = [
    AES_ROOT / "data" / "aes_testplan.hjson",
    AES_ROOT / "data" / "aes_sec_cm_testplan.hjson",
]
DV_TESTS_DIR = AES_ROOT / "dv" / "tests"
DV_ENV_DIR = AES_ROOT / "dv" / "env"
DV_COV_DIR = AES_ROOT / "dv" / "cov"
MODEL_DIR = AES_ROOT / "model"
DPI_SV_DIR = AES_ROOT / "dv" / "aes_model_dpi"
SW_TEST_DIRS = [
    OT_ROOT / "sw" / "device" / "tests",
]


def main() -> None:
    if not RTL_DIR.exists():
        raise SystemExit(f"OpenTitan AES RTL not found at: {RTL_DIR}\n"
                         f"Set KGWEAVE_OPENTITAN_ROOT or clone opentitan.")

    sv_files = sorted(RTL_DIR.glob("*.sv"))
    bind_sva_files = sorted(BIND_SVA_DIR.glob("*.sv")) if BIND_SVA_DIR.exists() else []
    cov_files = sorted(COV_DIR.glob("*.sv")) if COV_DIR.exists() else []
    print(f"Found {len(sv_files)} SystemVerilog files in {RTL_DIR}")
    if bind_sva_files:
        print(f"Found {len(bind_sva_files)} bind-SVA files in {BIND_SVA_DIR}: "
              f"{[f.name for f in bind_sva_files]}")
    if cov_files:
        print(f"Found {len(cov_files)} dv/cov files in {COV_DIR}: "
              f"{[f.name for f in cov_files]}")

    schema = load_schema(str(SCHEMA))
    # Larger min-size suppresses Leiden's long tail of micro-clusters that
    # would otherwise overflow the colour palette and hide the macro structure.
    # Opt into the OpenTitan profile explicitly so SW→RTL resolution and
    # Bazel reader source their patterns from project_conventions rather
    # than legacy hardcoded defaults (Phase 2 hardcoded-values cleanup).
    config = KGConfig(
        community_min_size=8,
        community_resolution=0.7,
        project_conventions=ProjectConventions.opentitan(),
    )
    backend = NetworkXBackend()

    # 1) Per-file structural extraction via pyslang syntax tree
    parser = SVParserExtractor(schema=schema, config=config)
    total_entities = 0
    total_triples = 0
    all_sv_files = sv_files + bind_sva_files
    for sv in all_sv_files:
        text = sv.read_text(errors="replace")
        result = parser.extract(text=text, source=str(sv))
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)
        total_entities += len(result.entities)
        total_triples += len(result.triples)
    print(f"parser_extractor: {total_entities} entities, "
          f"{total_triples} triples across {len(all_sv_files)} files")

    # 2) Best-effort slang elaboration. OpenTitan needs include paths /
    # packages we may not have wired up here, so we don't fail the demo if
    # elaboration errors out — we just skip the hierarchy/connectivity pass.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Stubs must come first so uvm_pkg / dv_utils_pkg are defined before any
    # file that imports them.
    stub_files = sorted(SV_STUBS_DIR.glob("*.sv")) if SV_STUBS_DIR.exists() else []
    all_elab_files = stub_files + sv_files + bind_sva_files + cov_files
    FILELIST.write_text("\n".join(str(p) for p in all_elab_files) + "\n")
    try:
        # OpenTitan AES files do `\`include "prim_assert.sv"` and use
        # `\`ASSERT(...)` macros that only expand when `INC_ASSERT` is
        # predefined and `prim/rtl/` is on the include search path.
        # Without this wiring slang silently produces 0 SVA_Assertion
        # entities (the macros expand to empty bodies).
        #
        # Beyond `INC_ASSERT` we also enable `FPV_ON` (surfaces formal-only
        # `\`ifdef FPV_ON` assertion blocks; note this *suppresses* a few
        # `ASSERT_KNOWN`/`ASSERT_FINAL` bodies that are wrapped in
        # `\`ifndef FPV_ON`, but the FPV-specific gains outweigh the loss
        # on AES) and `SIMULATION` (enables `prim_flop_macros.sv`'s
        # simulation-only sparse-FSM assertion paths). `SYNTHESIS` is left
        # *undefined* on purpose — its `\`ifndef SYNTHESIS` blocks are the
        # active path and would otherwise be eliminated. `UVM` is not
        # defined: enabling it pulls in `uvm_pkg::*` references that slang
        # cannot resolve here, dropping the count to zero. `EN_MASKING` is
        # defined to surface the conditional `aes_masking_reseed_if` bind
        # (guarded by `` `if (`EN_MASKING) `` in `aes_bind.sv`).
        prim_rtl = OT_ROOT / "hw" / "ip" / "prim" / "rtl"
        incdirs = [str(prim_rtl)] if prim_rtl.exists() else []
        # dv_fcov_macros.svh is included by aes_cov_if.sv — add its directory.
        if DV_UTILS_INC_DIR.exists():
            incdirs.append(str(DV_UTILS_INC_DIR))
        analyzer = SlangHierarchyAnalyzer(
            filelist_path=str(FILELIST),
            backend=backend,
            top_module="aes",
            incdirs=incdirs if incdirs else None,
            defines=["INC_ASSERT", "FPV_ON", "SIMULATION", "EN_MASKING"],
        )
        slang_result = analyzer.analyze_full()
        backend.upsert_entities(slang_result.entities)
        backend.upsert_triples(slang_result.triples)
        n_clock = sum(1 for e in slang_result.entities if e.type == "ClockDomain")
        n_reset = sum(1 for e in slang_result.entities if e.type == "ResetDomain")
        n_clocked_by = sum(1 for t in slang_result.triples if t.predicate == "clocked_by")
        n_reset_by = sum(1 for t in slang_result.triples if t.predicate == "reset_by")
        n_sva = sum(1 for e in slang_result.entities if e.type == "SVA_Assertion")
        n_has_assert = sum(1 for t in slang_result.triples if t.predicate == "has_assertion")
        n_ref_signal = sum(1 for t in slang_result.triples if t.predicate == "references_signal")
        n_fsm = sum(1 for e in slang_result.entities if e.type == "FSM")
        n_fsm_state = sum(1 for e in slang_result.entities if e.type == "FSM_State")
        n_has_fsm = sum(1 for t in slang_result.triples if t.predicate == "has_fsm")
        n_has_state = sum(1 for t in slang_result.triples if t.predicate == "has_state")
        n_trans = sum(1 for t in slang_result.triples if t.predicate == "transitions_to")
        n_reads = sum(1 for t in slang_result.triples if t.predicate == "reads")
        n_cg_sv = sum(1 for e in slang_result.entities if e.type == "Covergroup_SV")
        n_cp = sum(1 for e in slang_result.entities if e.type == "Coverpoint")
        n_cb = sum(1 for e in slang_result.entities if e.type == "CoverBin")
        n_cx = sum(1 for e in slang_result.entities if e.type == "CoverCross")
        n_sample_arg = sum(
            1 for e in slang_result.entities if e.type == "Covergroup_SampleArg"
        )
        n_observes = sum(1 for t in slang_result.triples if t.predicate == "observes")
        n_has_sample_arg = sum(
            1 for t in slang_result.triples if t.predicate == "has_sample_arg"
        )
        n_bound_into = sum(1 for t in slang_result.triples if t.predicate == "bound_into")
        print(f"slang: {len(slang_result.triples)} hierarchy/connectivity triples, "
              f"{n_clock} ClockDomain + {n_reset} ResetDomain entities, "
              f"{n_clocked_by} clocked_by + {n_reset_by} reset_by edges, "
              f"{n_sva} SVA_Assertion entities, "
              f"{n_has_assert} has_assertion + {n_ref_signal} references_signal edges, "
              f"{n_fsm} FSM + {n_fsm_state} FSM_State entities, "
              f"{n_has_fsm} has_fsm + {n_has_state} has_state + {n_trans} transitions_to edges, "
              f"{n_reads} reads (intra-module dataflow) edges, "
              f"{n_cg_sv} Covergroup_SV + {n_cp} Coverpoint + {n_cb} CoverBin + "
              f"{n_cx} CoverCross + {n_sample_arg} Covergroup_SampleArg + "
              f"{n_observes} observes + {n_has_sample_arg} has_sample_arg edges, "
              f"{n_bound_into} bound_into edges")
        bound_into_triples = [
            t for t in slang_result.triples if t.predicate == "bound_into"
        ]
        if bound_into_triples:
            print(f"  bind directives ({len(bound_into_triples)}):")
            for t in bound_into_triples:
                ev = f"  [u={t.evidence_span}]" if t.evidence_span else ""
                print(f"    {t.subject}  bound_into  {t.object}{ev}")
        # AES dv/cov/ — covergroup extraction delta.
        # uvm_pkg / dv_utils_pkg are stubbed in data/sv_stubs/ so these files
        # can now elaborate alongside the RTL filelist.
        if cov_files:
            n_cg_sv_new = sum(
                1 for e in slang_result.entities if e.type == "Covergroup_SV"
            )
            n_cp_new = sum(
                1 for e in slang_result.entities if e.type == "Coverpoint"
            )
            n_cx_new = sum(
                1 for e in slang_result.entities if e.type == "CoverCross"
            )
            n_cb_new = sum(
                1 for e in slang_result.entities if e.type == "CoverBin"
            )
            cg_names = sorted(
                e.name for e in slang_result.entities if e.type == "Covergroup_SV"
            )
            print(f"  dv/cov/ elaborated: {len(cov_files)} files "
                  f"({[f.name for f in cov_files]})")
            print(f"  dv/cov/ delta: {n_cg_sv_new} Covergroup_SV, "
                  f"{n_cp_new} Coverpoint, {n_cx_new} CoverCross, "
                  f"{n_cb_new} CoverBin")
            if cg_names:
                print(f"  covergroup names ({len(cg_names)}): {cg_names}")
        if bind_sva_files:
            bind_sva_modules = {
                "aes_idle_check", "aes_reseed_if", "aes_masking_reseed_if",
            }
            bind_svas = [
                e for e in slang_result.entities
                if e.type == "SVA_Assertion"
                and e.name.split(".")[0] in bind_sva_modules
            ]
            print(f"  bind-SVA files included: "
                  f"{[f.name for f in bind_sva_files]}")
            print(f"  bind-SVA files skipped: aes_bind.sv binds "
                  f"tlul_assert (needs tlul_pkg) and aes_csr_assert_fpv "
                  f"(not in data) — those two directives are silently "
                  f"unresolved; the module aes_bind itself elaborates fine")
            print(f"  bind-attached SVAs ({len(bind_svas)}):")
            for e in bind_svas:
                src = (e.sources or ["?"])[0] if e.sources else "?"
                print(f"    {e.name}  [{src}]")
    except Exception as exc:  # noqa: BLE001 — demo should not hard-fail
        print(f"slang elaboration skipped: {type(exc).__name__}: {exc}")

    # 2b) Intra-module dataflow extraction (drives_signal + Process entities).
    # Runs AFTER slang/parser so the module-signal table is populated.
    try:
        from kgweave.knowledge_graph.extraction import SVDataflowExtractor

        signal_table: dict[str, set[str]] = {}
        for ent in backend.get_all_entities():
            if ent.type == "RTL_Module":
                signal_table.setdefault(ent.name, set())
            elif ent.type in ("Port", "Signal") and "." in ent.name:
                mod, sig = ent.name.split(".", 1)
                signal_table.setdefault(mod, set()).add(sig)
        df_extractor = SVDataflowExtractor(known_module_signals=signal_table)
        n_drives = 0
        n_proc = 0
        modules_with_drives: set[str] = set()
        df_triples_all: list = []
        for sv in all_sv_files:
            text = sv.read_text(errors="replace")
            res = df_extractor.extract(text=text, source=str(sv))
            backend.upsert_entities(res.entities)
            backend.upsert_triples(res.triples)
            n_proc += sum(1 for e in res.entities if e.type == "Process")
            for t in res.triples:
                if t.predicate == "drives_signal":
                    n_drives += 1
                    modules_with_drives.add(t.subject.split(".", 1)[0])
                    df_triples_all.append(t)
        print(
            f"sv_dataflow: emitted {n_drives} drives_signal edges across "
            f"{len(modules_with_drives)} modules; {n_proc} Process entities."
        )

        # 2c) v2 AST decomposition (Operator/Literal/Index + If/Case/Loop/
        # Branch/Assignment/Condition). Tagged ``layer="ast"`` so default
        # consumers ignore it; gated by KGConfig.enable_ast_decomposition.
        if getattr(config, "enable_ast_decomposition", True):
            try:
                from kgweave.knowledge_graph.extraction import V2IntegrationDriver

                v2 = V2IntegrationDriver(known_module_signals=signal_table)
                ast_ents = 0
                ast_trips = 0
                for sv in all_sv_files:
                    text = sv.read_text(errors="replace")
                    r = v2.extract(text=text, source=str(sv))
                    backend.upsert_entities(r.entities)
                    backend.upsert_triples(r.triples)
                    ast_ents += sum(1 for e in r.entities
                                    if getattr(e, "layer", None) == "ast")
                    ast_trips += sum(1 for t in r.triples
                                     if getattr(t, "layer", None) == "ast")
                print(
                    f"sv_v2_integration: emitted {ast_ents} ast-layer entities "
                    f"and {ast_trips} ast-layer triples."
                )
            except Exception as exc:  # noqa: BLE001
                print(f"sv_v2_integration skipped: {type(exc).__name__}: {exc}")
        # Showcase: pick a target signal and print its one-hop reverse drivers.
        if df_triples_all:
            # Prefer a signal that has the most direct drivers for the report.
            from collections import Counter
            target_counts = Counter(t.object for t in df_triples_all)
            chosen, _ = target_counts.most_common(1)[0]
            drivers = sorted({t.subject for t in df_triples_all if t.object == chosen})
            head = drivers[:8]
            more = "" if len(drivers) <= 8 else f" (+{len(drivers) - 8} more)"
            print(f"  reverse drivers of {chosen}: {head}{more}")
    except Exception as exc:  # noqa: BLE001
        print(f"sv_dataflow skipped: {type(exc).__name__}: {exc}")

    # 3) HJSON CSR extraction — software-visible register interface
    if HJSON_PATH.exists():
        csr = HJSONCSRExtractor(schema=schema, config=config)
        csr_result = csr.extract(text=HJSON_PATH.read_text(), source=str(HJSON_PATH))
        backend.upsert_entities(csr_result.entities)
        backend.upsert_triples(csr_result.triples)
        print(f"hjson_csr: {len(csr_result.entities)} entities, "
              f"{len(csr_result.triples)} triples from {HJSON_PATH.name}")
    else:
        print(f"hjson_csr: skipped (no {HJSON_PATH})")

    # 4) Markdown doc fusion — fold doc/*.md into the existing entity index.
    # Constructor takes the names known so far so we can fuse references
    # back into existing module entities (case-insensitive dedup in backend).
    if DOC_DIR.exists():
        known_names = list(backend.get_all_node_names_and_aliases().keys())
        doc_extractor = MarkdownDocExtractor(known_entity_names=known_names)
        md_files = sorted(DOC_DIR.glob("*.md"))
        md_entities = md_triples = 0
        for md in md_files:
            r = doc_extractor.extract(text=md.read_text(errors="replace"),
                                      source=str(md))
            backend.upsert_entities(r.entities)
            backend.upsert_triples(r.triples)
            md_entities += len(r.entities)
            md_triples += len(r.triples)
        print(f"markdown_doc: {md_entities} entities, {md_triples} triples "
              f"across {len(md_files)} doc files")
    else:
        print(f"markdown_doc: skipped (no {DOC_DIR})")

    # 4b) SDC timing-constraint fusion — anchor timing intent to ports/clocks.
    if SDC_PATH.exists():
        known_names = list(backend.get_all_node_names_and_aliases().keys())
        sdc = SDCExtractor(known_entity_names=known_names,
                           schema=schema, config=config)
        sdc_result = sdc.extract(text=SDC_PATH.read_text(),
                                 source=str(SDC_PATH))
        backend.upsert_entities(sdc_result.entities)
        backend.upsert_triples(sdc_result.triples)
        print(f"sdc: {len(sdc_result.entities)} entities, "
              f"{len(sdc_result.triples)} triples from {SDC_PATH.name}")
    else:
        print(f"sdc: skipped (no {SDC_PATH})")

    # 4b') IP-XACT structural fusion — declarative source of truth for
    # ports / clocks / resets / registers / fields / bus interfaces.
    # Drives the cross-source completeness audit ("does the RTL implement
    # everything IP-XACT declares?").
    ipxact_result = None
    if IPXACT_PATH.exists():
        known_names = list(backend.get_all_node_names_and_aliases().keys())
        ipxact = IPXACTExtractor(known_entity_names=known_names,
                                 schema=schema, config=config)
        ipxact_result = ipxact.extract(text=IPXACT_PATH.read_text(),
                                       source=str(IPXACT_PATH))
        backend.upsert_entities(ipxact_result.entities)
        backend.upsert_triples(ipxact_result.triples)
        n_specs = sum(1 for t in ipxact_result.triples
                      if t.predicate == "specifies")
        print(f"ipxact: {len(ipxact_result.entities)} entities, "
              f"{len(ipxact_result.triples)} triples "
              f"({n_specs} specifies edges) from {IPXACT_PATH.name}")
        # Audit query: enumerate IPXACT_Ports and check whether each has a
        # specifies edge to a canonical Port. Unmatched ports are
        # candidate gaps (or IP-XACT-only declarations) the audit surfaces.
        ipxact_ports = [e for e in ipxact_result.entities
                        if e.type == "IPXACT_Port"]
        unmatched = [
            e for e in ipxact_ports
            if not any(
                t.predicate == "specifies"
                for t in backend.get_outgoing_edges(e.name)
            )
        ]
        print(f"  ipxact audit: {len(unmatched)} of {len(ipxact_ports)} "
              f"IPXACT_Ports have no matching RTL port (potential gaps)")
        sample_specs = [
            t for t in ipxact_result.triples
            if t.predicate == "specifies"
            and t.subject.startswith("aes.ipxact_port.")
        ][:5]
        if sample_specs:
            print("  sample specifies edges (IPXACT_Port -> Port):")
            for t in sample_specs:
                print(f"    ({t.subject!r}, 'specifies', {t.object!r})")
        # Phase-2 entity / edge counts (address blocks, field enums,
        # parameters, file sets) — surface what the new extractor wedge
        # contributes to the completeness audit.
        n_addr_block = sum(
            1 for e in ipxact_result.entities
            if e.type == "IPXACT_AddressBlock"
        )
        n_field_enum = sum(
            1 for e in ipxact_result.entities
            if e.type == "IPXACT_FieldEnum"
        )
        n_param = sum(
            1 for e in ipxact_result.entities
            if e.type == "IPXACT_Parameter"
        )
        n_fileset = sum(
            1 for e in ipxact_result.entities
            if e.type == "IPXACT_FileSet"
        )
        n_contains_register = sum(
            1 for t in ipxact_result.triples
            if t.predicate == "contains_register"
        )
        n_has_enum = sum(
            1 for t in ipxact_result.triples
            if t.predicate == "has_ipxact_enum"
        )
        n_parameterizes = sum(
            1 for t in ipxact_result.triples
            if t.predicate == "parameterizes"
        )
        n_implemented_by = sum(
            1 for t in ipxact_result.triples
            if t.predicate == "implemented_by"
        )
        print(
            f"  ipxact phase-2: addr_block={n_addr_block} "
            f"(contains_register={n_contains_register}), "
            f"field_enum={n_field_enum} "
            f"(has_ipxact_enum={n_has_enum}), "
            f"param={n_param} (parameterizes={n_parameterizes}), "
            f"fileset={n_fileset} (implemented_by={n_implemented_by})"
        )
        # Phase-2b bus-interface fusion: busType / portMap / memoryMap chain.
        n_bus_type = sum(1 for e in ipxact_result.entities
                         if e.type == "IPXACT_BusType")
        n_logical_port = sum(1 for e in ipxact_result.entities
                             if e.type == "IPXACT_LogicalPort")
        n_memmap = sum(1 for e in ipxact_result.entities
                       if e.type == "IPXACT_MemoryMap")
        n_addr_space = sum(1 for e in ipxact_result.entities
                           if e.type == "IPXACT_AddressSpace")
        n_aggregates_port = sum(1 for t in ipxact_result.triples
                                if t.predicate == "aggregates_port")
        n_conforms_to = sum(1 for t in ipxact_result.triples
                            if t.predicate == "conforms_to")
        n_exposes_memmap = sum(1 for t in ipxact_result.triples
                               if t.predicate == "exposes_memory_map")
        print(
            f"  ipxact phase-2b: bus_type={n_bus_type} "
            f"(conforms_to={n_conforms_to}), "
            f"logical_port={n_logical_port} "
            f"(aggregates_port={n_aggregates_port}), "
            f"memmap={n_memmap} (exposes_memory_map={n_exposes_memmap}), "
            f"addr_space={n_addr_space}"
        )
        # Audit signal: aggregates_port edges whose object is the bare
        # physical name (i.e. fusion to a canonical Port failed). These are
        # the "missing" RTL ports the audit should surface.
        unfused_agg = [
            t for t in ipxact_result.triples
            if t.predicate == "aggregates_port" and "." not in t.object
        ]
        if unfused_agg:
            print(
                f"  ipxact audit: {len(unfused_agg)} aggregates_port edges "
                "land on bare physical names (fusion failed -> orphan RTL ports):"
            )
            for t in unfused_agg[:5]:
                print(f"    {t.subject!r} aggregates_port {t.object!r}")
    else:
        print(f"ipxact: skipped (no {IPXACT_PATH})")

    # 4c) DV testplan fusion — fold testpoints + covergroups into the KG.
    available_testplans = [p for p in TESTPLAN_PATHS if p.exists()]
    if available_testplans:
        known_names = list(backend.get_all_node_names_and_aliases().keys())
        tp_extractor = TestplanExtractor(known_entity_names=known_names,
                                         schema=schema, config=config)
        tp_entities = tp_triples = 0
        sample_tests_edges = []
        sample_mentions_edges = []
        sample_covers_edges = []
        pred_counts: dict = {}
        for tp_path in available_testplans:
            r = tp_extractor.extract(text=tp_path.read_text(errors="replace"),
                                     source=str(tp_path))
            backend.upsert_entities(r.entities)
            backend.upsert_triples(r.triples)
            tp_entities += len(r.entities)
            tp_triples += len(r.triples)
            for t in r.triples:
                pred_counts[t.predicate] = pred_counts.get(t.predicate, 0) + 1
            sample_tests_edges.extend(
                [t for t in r.triples if t.predicate == "tests"]
            )
            sample_mentions_edges.extend(
                [t for t in r.triples if t.predicate == "mentions"]
            )
            sample_covers_edges.extend(
                [t for t in r.triples if t.predicate == "covers"]
            )
        print(f"testplan: {tp_entities} entities, {tp_triples} triples "
              f"from {len(available_testplans)} files")
        print(f"  testplan predicate breakdown: {pred_counts}")
        if sample_tests_edges:
            print("  sample testpoint -> test edges (first 5):")
            for t in sample_tests_edges[:5]:
                print(f"    ({t.subject!r}, 'tests', {t.object!r})")
        if sample_mentions_edges:
            print(f"  sample testpoint -> mentions edges "
                  f"({len(sample_mentions_edges)} total, first 5):")
            for t in sample_mentions_edges[:5]:
                print(f"    ({t.subject!r}, 'mentions', {t.object!r})")
        else:
            print("  testpoint -> mentions edges: 0")
        if sample_covers_edges:
            print(f"  sample testpoint -> covers edges "
                  f"({len(sample_covers_edges)} total, first 5):")
            for t in sample_covers_edges[:5]:
                print(f"    ({t.subject!r}, 'covers', "
                      f"{t.object!r}) [{t.evidence_span}]")
        else:
            print("  testpoint -> covers edges: 0")
    else:
        print(f"testplan: skipped (no testplan hjson found)")

    # 4d) DV test file realization — map test files to DVTest entities.
    if DV_TESTS_DIR.exists():
        known_names = list(backend.get_all_node_names_and_aliases().keys())
        realizer = DVTestRealizationExtractor(known_entity_names=known_names)
        r = realizer.extract(text="", source=str(DV_TESTS_DIR))
        backend.upsert_entities(r.entities)
        backend.upsert_triples(r.triples)
        n_real = sum(1 for t in r.triples if t.predicate == "realized_by")
        n_files = sum(1 for e in r.entities if e.type == "SV_File")
        orphans = n_files - n_real
        sample_realized = [t for t in r.triples if t.predicate == "realized_by"][:5]
        print(f"dv_test_realization: {n_files} SV_File entities, "
              f"{n_real} realized_by edges, {orphans} orphan files from {DV_TESTS_DIR.name}")
        if sample_realized:
            print("  sample realized_by edges (first 5):")
            for t in sample_realized:
                print(f"    ({t.subject!r}, 'realized_by', {t.object!r})")
    else:
        print(f"dv_test_realization: skipped (no {DV_TESTS_DIR})")

    # 4e) C/C++ reference model and DPI-C boundary extraction
    if MODEL_DIR.exists():
        # DPI-C boundary extraction: regex pass over SV files in dv/aes_model_dpi/
        dpi_names: list = []
        if DPI_SV_DIR.exists():
            sv_list = [str(p) for p in sorted(DPI_SV_DIR.glob("*.sv"))]
            scoped_imports = extract_dpi_boundaries_with_scope(sv_list)
            # Backward-compat flat list for cpp extractor name-matching
            dpi_names = list({dpi for _sn, _sk, dpi in scoped_imports})
            if scoped_imports:
                dpi_result = build_dpi_boundary_entities(
                    scoped_imports=scoped_imports,
                    sv_source=str(DPI_SV_DIR),
                )
                backend.upsert_entities(dpi_result.entities)
                backend.upsert_triples(dpi_result.triples)
                n_imports_dpi = sum(
                    1 for t in dpi_result.triples if t.predicate == "imports_dpi"
                )
                # Breakdown by scope name
                scope_counts: dict = {}
                for sn, _sk, _dn in scoped_imports:
                    scope_counts[sn] = scope_counts.get(sn, 0) + 1
                scope_str = ", ".join(
                    f"{sn}: {cnt} imports" for sn, cnt in sorted(scope_counts.items())
                )
                print(
                    f"dpi_boundary: {len(dpi_names)} DPIBoundary entities, "
                    f"{n_imports_dpi} imports_dpi edges  [{scope_str}]"
                )
            else:
                print(f"dpi_boundary: 0 import \"DPI-C\" declarations found in {DPI_SV_DIR}")
        else:
            print(f"dpi_boundary: skipped (no {DPI_SV_DIR})")

        known_names = list(backend.get_all_node_names_and_aliases().keys())
        known_for_cpp = list(set(known_names) | set(dpi_names))
        cpp = CppRefModelExtractor(known_entity_names=known_for_cpp)
        r = cpp.extract(source=str(MODEL_DIR))
        backend.upsert_entities(r.entities)
        backend.upsert_triples(r.triples)
        n_cfiles = sum(1 for e in r.entities if e.type == "CFile")
        n_cfuncs = sum(1 for e in r.entities if e.type == "CFunction")
        n_dpi = sum(1 for t in r.triples if t.predicate == "implements_dpi")
        print(f"cpp_ref_model: {n_cfiles} CFile, {n_cfuncs} CFunction, "
              f"{n_dpi} implements_dpi edges from {MODEL_DIR}")

        # Also scan dv/aes_model_dpi/ C files for DPI wrapper functions.
        if DPI_SV_DIR.exists():
            dpi_c_files = list(DPI_SV_DIR.glob("*.c")) + list(DPI_SV_DIR.glob("*.h"))
            if dpi_c_files:
                cpp_dpi = CppRefModelExtractor(known_entity_names=known_for_cpp)
                r_dpi = cpp_dpi.extract(source=str(DPI_SV_DIR))
                backend.upsert_entities(r_dpi.entities)
                backend.upsert_triples(r_dpi.triples)
                n_dpi_c = sum(1 for e in r_dpi.entities if e.type == "CFile")
                n_dpi_f = sum(1 for e in r_dpi.entities if e.type == "CFunction")
                n_dpi_edges = sum(1 for t in r_dpi.triples if t.predicate == "implements_dpi")
                print(f"  dpi_wrapper: {n_dpi_c} CFile, {n_dpi_f} CFunction, "
                      f"{n_dpi_edges} implements_dpi from {DPI_SV_DIR.name}")
    else:
        print(f"cpp_ref_model: skipped (no {MODEL_DIR})")

    # 4f) SW regression test extraction (Tier A patterns + Tier B build-system).
    # Loads the OpenTitan-flavored YAML so dvsim_hjson and bazel readers are
    # enabled by default; passes project_root=OT_ROOT so those readers can
    # walk the dvsim cfgs and BUILD files.
    sw_extracted = False
    from kgweave.knowledge_graph.common.sw_test_config import load_sw_test_config

    sw_yaml = REPO / "config" / "sw_test_resolution.yaml"
    sw_cfg = load_sw_test_config(str(sw_yaml)) if sw_yaml.exists() else None
    for sw_dir in SW_TEST_DIRS:
        if sw_dir.exists():
            known_names = list(backend.get_all_node_names_and_aliases().keys())
            sw_extractor = SWTestExtractor(
                known_entity_names=known_names,
                sw_test_config=sw_cfg,
            )
            r_sw = sw_extractor.extract(
                source=str(sw_dir),
                project_root=OT_ROOT if OT_ROOT.exists() else None,
            )
            backend.upsert_entities(r_sw.entities)
            backend.upsert_triples(r_sw.triples)
            n_tests = sum(1 for e in r_sw.entities if e.type == "SW_Test")
            n_tests_mod = sum(1 for t in r_sw.triples if t.predicate == "tests_module")
            n_csr = sum(1 for t in r_sw.triples if t.predicate == "accesses_csr")
            aes_tests = [
                e.name for e in r_sw.entities
                if e.type == "SW_Test" and "aes" in e.name.lower()
            ]
            print(f"sw_test: {n_tests} SW_Test entities, {n_tests_mod} tests_module, "
                  f"{n_csr} accesses_csr edges from {sw_dir}")
            if aes_tests:
                print(f"  aes-related tests ({len(aes_tests)}): {aes_tests[:8]}"
                      f"{'...' if len(aes_tests) > 8 else ''}")
            sw_extracted = True
            break
    if not sw_extracted:
        print("sw_test: skipped (no sw/device/tests directory found)")

    # 4g) UVM sample-callsite extraction — closes the audit chain
    # RTL_Module -> Covergroup_SV -> UVMSampleCallsite. Walks env/ and cov/
    # together so wrappers in aes_cov_if.sv are visible when scanning callsites
    # in aes_scoreboard.sv. Uses pyslang's parser-only mode (UVM elaboration
    # would fail because uvm_pkg base classes aren't in our parse set).
    uvm_dirs = [d for d in (DV_ENV_DIR, DV_COV_DIR) if d.exists()]
    if uvm_dirs:
        all_entities = backend.get_all_entities()
        known_cgs = [e.name for e in all_entities if e.type == "Covergroup_SV"]
        known_args = [e.name for e in all_entities if e.type == "Covergroup_SampleArg"]
        uvm_ext = UVMSampleExtractor(
            known_covergroups=known_cgs,
            known_sample_args=known_args,
        )
        r_uvm = uvm_ext.extract_directory(uvm_dirs)
        backend.upsert_entities(r_uvm.entities)
        backend.upsert_triples(r_uvm.triples)
        n_callsite = sum(1 for e in r_uvm.entities if e.type == "UVMSampleCallsite")
        n_wrapper = sum(1 for e in r_uvm.entities if e.type == "UVMSampleWrapper")
        n_argexpr = sum(1 for e in r_uvm.entities if e.type == "UVMSampleArgExpr")
        n_samples = sum(1 for t in r_uvm.triples if t.predicate == "samples_covergroup")
        n_via = sum(1 for t in r_uvm.triples if t.predicate == "via_wrapper")
        n_wraps = sum(1 for t in r_uvm.triples if t.predicate == "wraps_covergroup")
        n_binds = sum(1 for t in r_uvm.triples if t.predicate == "binds_to_arg")
        print(
            f"uvm_sample: {n_callsite} UVMSampleCallsite, {n_wrapper} UVMSampleWrapper, "
            f"{n_argexpr} UVMSampleArgExpr, {n_samples} samples_covergroup, "
            f"{n_via} via_wrapper, {n_wraps} wraps_covergroup, "
            f"{n_binds} binds_to_arg edges"
        )
        # Wrapper-to-covergroup mapping (one-line audit summary).
        wraps = sorted(
            (t.subject, t.object)
            for t in r_uvm.triples if t.predicate == "wraps_covergroup"
        )
        if wraps:
            print(f"  wrapper -> covergroup ({len(wraps)}):")
            for sub, obj in wraps:
                print(f"    {sub.split('::', 1)[-1]:<28} -> {obj}")
        # Audit verdict: every Covergroup_SV must have at least one
        # samples_covergroup edge or it is structurally orphan in the testbench.
        sampled = {t.object for t in r_uvm.triples if t.predicate == "samples_covergroup"}
        all_cgs = sorted(set(known_cgs))
        sampled_n = sum(1 for cg in all_cgs if cg in sampled)
        orphans = [cg for cg in all_cgs if cg not in sampled]
        print(
            f"  audit verdict: {sampled_n}/{len(all_cgs)} AES covergroups have "
            f"at least one samples_covergroup edge -> {len(orphans)} orphan "
            f"covergroups: {orphans}"
        )
    else:
        print(f"uvm_sample: skipped (no {DV_ENV_DIR} or {DV_COV_DIR})")

    # 4h) RTL_Module reachability tag — surfaces filelist-vs-elaboration gap.
    # Why: the parser-extractor emits RTL_Module nodes for every .sv on the
    # filelist, but slang only reaches modules wired in from the top.
    # Unreachable modules are audit signal ("you have N alternates on disk
    # but this build instantiates exactly one"), so we tag rather than drop.
    reachable = backend.compute_rtl_reachability("aes")
    rtl_module_names = [
        n for n, d in backend.graph.nodes(data=True)
        if d.get("type") == "RTL_Module"
    ]
    n_reach = 0
    n_unreach = 0
    unreach_names: list = []
    for name in rtl_module_names:
        node = backend.graph.nodes[name]
        is_reach = name in reachable
        node.setdefault("aliases", [])
        # Strip any prior reachable= tag (idempotent across re-runs) and
        # write the current verdict as a structured alias entry.
        node["aliases"] = [
            a for a in node["aliases"]
            if not (isinstance(a, str) and a.startswith("reachable="))
        ]
        node["aliases"].append(f"reachable={'true' if is_reach else 'false'}")
        if is_reach:
            n_reach += 1
        else:
            n_unreach += 1
            unreach_names.append(name)
    print(
        f"\nRTL_Module reachability from aes: {n_reach} reachable, "
        f"{n_unreach} unreachable. Top 5 unreachable: "
        f"{sorted(unreach_names)[:5]}"
    )

    # 4i) Audit/coverage views — precision (orphan tests) + recall
    # (RTL_Module coverage gaps). Pipeline ordering note: this MUST run
    # after the SW_Test extractor (step 4f) and after RTL parsing (steps
    # 1-2), because both query helpers read backend node/edge state
    # populated by those earlier passes. The SW_Test extractor itself
    # raises ValueError when known_entity_names is empty, which is the
    # runtime safety net for misordering.
    from kgweave.knowledge_graph import (
        audit_orphan_tests,
        coverage_gaps_by_target,
        coverage_gaps_by_target_transitive,
    )

    coverage_gaps = coverage_gaps_by_target(
        backend, node_type="RTL_Module", min_confidence="medium",
    )
    print("\n=== Test Completeness (RTL_Module coverage gaps, min=medium) ===")
    print(f"{len(coverage_gaps)} RTL_Module entities with no medium+ "
          f"tests_module coverage:")
    for name in coverage_gaps:
        print(f"  - {name}")

    transitive_gaps = coverage_gaps_by_target_transitive(
        backend, node_type="RTL_Module", min_confidence="medium",
    )
    print("\n=== Test Completeness — TRANSITIVE (RTL_Module gaps not covered "
          "by ancestor, min=medium) ===")
    print(f"{len(transitive_gaps)} RTL_Module entities with no direct OR "
          f"transitive medium+ coverage:")
    for name in transitive_gaps:
        print(f"  - {name}")
    print("  note: Transitive view considers a module covered if any ancestor "
          "module instantiated by a chain leading to it has a tests_module "
          "edge meeting the floor.")

    orphan_tests = audit_orphan_tests(backend)
    print("\n=== Audit Orphan Tests (precision view) ===")
    print(f"{len(orphan_tests)} SW_Test entities flagged is_test=True with "
          f"no resolved tests_module:")
    for name in orphan_tests:
        print(f"  - {name}")

    print("\n  legend: min_confidence='medium' excludes low-tier "
          "(filename-heuristic-only) edges; this is the precision-leaning "
          "floor for the completeness view.")

    # 5) Leiden community detection (no LLM, structural-only)
    detector = CommunityDetector(backend=backend, config=config)
    communities = detector.detect()
    print(f"leiden: {len(communities)} communities detected")

    # Whitelist the entity types worth visualising — drop Signal noise but
    # surface the new CSR + doc Section entities so they appear in the graph.
    # Optional spec-claim layer (LLM-driven; off by default to keep the
    # demo deterministic and free of API costs). Enable with
    # KGWEAVE_DEMO_LLM=1 and an OPENAI_API_KEY in the environment.
    if os.environ.get("KGWEAVE_DEMO_LLM"):
        try:
            from kgweave.knowledge_graph.common.protocols import get_default_llm
            from kgweave.knowledge_graph.extraction import SpecClaimExtractor

            spec_md = AES_ROOT / "doc" / "theory_of_operation.md"
            if spec_md.exists():
                _client = get_default_llm()

                class _DemoLLMAdapter:
                    def generate(self, prompt: str) -> str:
                        resp = _client.json_completion(
                            [
                                {"role": "system",
                                 "content": "Return strict JSON only."},
                                {"role": "user", "content": prompt},
                            ]
                        )
                        return resp.content

                known_names = list(
                    backend.get_all_node_names_and_aliases().keys()
                )
                claim_extractor = SpecClaimExtractor(
                    llm_provider=_DemoLLMAdapter(),
                    known_entity_names=known_names,
                )
                r = claim_extractor.extract(
                    text=spec_md.read_text(), source=str(spec_md)
                )
                backend.upsert_entities(r.entities)
                backend.upsert_triples(r.triples)
                print(
                    f"llm_doc: {len(r.entities)} claim entities, "
                    f"{len(r.triples)} triples from {spec_md.name}"
                )
            else:
                print(f"llm_doc: skipped (no {spec_md})")
        except Exception as exc:
            print(f"llm_doc: skipped (provider unavailable: {exc})")
    else:
        print("llm_doc: skipped (set KGWEAVE_DEMO_LLM=1 to enable; "
              "requires OPENAI_API_KEY)")

    structural_types = [
        "RTL_Module", "Instance", "Port", "Parameter",
        "CSR_Register", "CSR_Field", "Section",
        "ClockDomain", "ResetDomain", "FSM", "FSM_State", "SVA_Assertion",
        "ClockConstraint", "IODelay", "FalsePath", "MulticyclePath", "ClockGroup",
        "Testpoint", "Covergroup", "Stage", "DVTest", "SV_File",
        "Covergroup_SV", "Coverpoint", "CoverBin", "CoverCross",
        "Covergroup_SampleArg",
        "IPXACT_Component", "IPXACT_Port", "IPXACT_Clock", "IPXACT_Reset",
        "IPXACT_Register", "IPXACT_Field", "IPXACT_BusInterface",
        "IPXACT_AddressBlock", "IPXACT_FieldEnum",
        "IPXACT_Parameter", "IPXACT_FileSet",
        "IPXACT_BusType", "IPXACT_LogicalPort",
        "IPXACT_MemoryMap", "IPXACT_AddressSpace",
        # Spec-claim layer (only populated when KGWEAVE_DEMO_LLM=1)
        "StructuralClaim", "BehavioralClaim", "ProtocolClaim", "SecurityClaim",
        # C/C++ ref-model and SW test layers
        "CFile", "CFunction", "DPIBoundary", "SW_Test",
        # UVM sample-callsite audit layer (Gap #3)
        "UVMSampleCallsite", "UVMSampleWrapper", "UVMSampleArgExpr",
    ]
    # Per-layer telemetry — proves layer-tag promotion works on real data.
    print("\nLayer breakdown (entities / triples per source-of-origin):")
    for layer in [
        "sv_parser",
        "slang",
        "hjson_csr",
        "markdown_doc",
        "sdc",
        "ipxact",
        "testplan",
        "dv_test_realization",
        "dpi_boundary",
        "cpp_ref_model",
        "sw_test",
        "uvm_sample",
        "llm_doc",
    ]:
        n_ents = len(backend.entities_by_layer(layer))
        n_trips = len(backend.triples_by_layer(layer))
        print(f"  layer {layer:14s}: {n_ents:5d} entities, {n_trips:5d} triples")

    # Sigma defaults to the structural-consumer view: the v2 ``ast`` layer
    # (Operator / Literal / Branch / Condition / IfStatement / etc.) is
    # hidden so the audit/DV/spec view stays uncluttered. To opt into the
    # RTL-debug view including expression internals, pass
    # ``include_layers={"slang", "ast"}`` (or ``"all"`` for every layer).
    n = export_html(
        backend=backend,
        output_path=str(OUT_HTML),
        include_types=structural_types,
        community_detector=detector,
    )
    print(f"\nExported {n} nodes → {OUT_HTML}")
    print(f"Open: file://{OUT_HTML}")

    # Sanity probe: pick a well-known AES signal and list a few inbound
    # `reads` edges (rhs -> lhs) to confirm dataflow is plausible.
    # Sanity probe: list a handful of `reads` triples from the slang result.
    sample_reads = [t for t in slang_result.triples if t.predicate == "reads"]
    if sample_reads:
        print("\nsample reads triples (first 5):")
        for t in sample_reads[:5]:
            print(f"  ({t.subject!r}, 'reads', {t.object!r})  "
                  f"lhs_slice={t.lhs_slice!r} rhs_slice={t.rhs_slice!r}  "
                  f"evidence={t.evidence_span!r}")
        sliced = [
            t for t in sample_reads
            if t.lhs_slice is not None or t.rhs_slice is not None
        ]
        print(f"\n  reads with non-null slice info: {len(sliced)} / "
              f"{len(sample_reads)}")
        if sliced:
            print("  sample sliced reads (first 3):")
            for t in sliced[:3]:
                print(f"    ({t.subject!r}, 'reads', {t.object!r})  "
                      f"lhs={t.lhs_slice!r} rhs={t.rhs_slice!r}")


if __name__ == "__main__":
    main()
