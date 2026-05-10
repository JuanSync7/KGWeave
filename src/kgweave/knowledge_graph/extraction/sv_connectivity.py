# @summary
# SystemVerilog hierarchy + connectivity extraction via pyslang elaboration.
# Produces canonical hierarchy edges (instantiates, instance_of, contains,
# part_of) plus connects_to with elaborated hierarchical paths.
# Exports: SlangHierarchyAnalyzer, SVConnectivityAnalyzer, SV_CONNECTIVITY_SOURCE
# Deps: pyslang (hard), kgweave.knowledge_graph.backend, kgweave.knowledge_graph.common
# @end-summary
"""SystemVerilog hierarchy + connectivity analyzer (pyslang-backed).

Uses ``pyslang.Compilation`` to elaborate a SystemVerilog design and emit
the canonical hierarchy edge set used by KGWeave:

* ``contains``     — module → port/signal/parameter (definition-level, namespaced as ``<module>.<name>``)
* ``instantiates`` — parent module definition → child module definition
* ``instance_of``  — hierarchical instance path → child module definition
* ``part_of``      — child instance hier path → enclosing instance hier path
* ``connects_to``  — instance port (``<inst_hier>.<port>``) ↔ net it binds to (hier path)

All triples carry ``extractor_source="slang"`` so the backend resolves
their confidence prior to ``1.0`` (deterministic elaborator).

Produces ONLY triples (no entity upserts) — the per-file tree-sitter parser
remains responsible for entity creation. This module's nodes are referenced
by name only; the backend auto-adds them on edge insertion when missing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

from kgweave.knowledge_graph.backend import GraphStorageBackend
from kgweave.knowledge_graph.common import Entity, Triple
from kgweave.knowledge_graph.common.schemas import ExtractionResult

# Heuristic for distinguishing reset signals from clocks in always_ff
# sensitivity lists. Pretty conservative — names like "rst", "rst_n",
# "reset", "por_n", "rst_lc_n" all match.
import re as _re

# Default reset-name heuristic (OpenTitan flavored: rst / reset / por).
# Codebases using ARM-style ``aresetn`` / ``nrst`` should override via the
# ``reset_signal_pattern`` constructor argument or
# ``KGConfig.reset_signal_pattern``.
_DEFAULT_RESET_PATTERN = r"(^|_)(rst|reset|por)(_|$)"
_RESET_NAME_RE = _re.compile(_DEFAULT_RESET_PATTERN, _re.IGNORECASE)
_IDENT_RE = _re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

__all__ = [
    "SlangHierarchyAnalyzer",
    "SVConnectivityAnalyzer",
    "SV_CONNECTIVITY_SOURCE",
]

logger = logging.getLogger("kgweave.knowledge_graph.extraction.slang")

# Synthetic source key for all slang-generated triples.
SV_CONNECTIVITY_SOURCE = "__sv_connectivity_batch__"

# Hard dependency: import errors here are fatal — caller is expected to
# install pyslang via the project's pyproject.toml.
import pyslang as _ps  # noqa: E402


class SlangHierarchyAnalyzer:
    """Cross-module SV hierarchy + connectivity analyzer (pyslang).

    Accepts a ``.f`` filelist path and an optional top module name. Reads
    every file referenced by the filelist (recursively, with ``+incdir+``
    support), elaborates the design via ``pyslang.Compilation``, and walks
    the resulting elaborated hierarchy.

    Produces only triples — no entity upserts — to prevent duplication
    with the per-file tree-sitter parser.
    """

    def __init__(
        self,
        filelist_path: str,
        backend: GraphStorageBackend,
        top_module: Optional[str] = None,
        incdirs: Optional[List[str]] = None,
        defines: Optional[List[str]] = None,
        reset_signal_pattern: Optional[str] = None,
        clock_signal_pattern: Optional[str] = None,
    ) -> None:
        self._filelist_path = filelist_path
        self._backend = backend
        self._top_module = top_module or ""
        # Reset-vs-clock classification regex for always_ff sensitivity-list
        # signals. ``None`` keeps the OpenTitan-flavored default; pass a
        # custom regex string for codebases using e.g. ARM AXI ``aresetn``.
        if reset_signal_pattern:
            try:
                self._reset_re = _re.compile(reset_signal_pattern, _re.IGNORECASE)
            except _re.error as exc:
                logger.warning(
                    "invalid reset_signal_pattern %r (%s); falling back to default",
                    reset_signal_pattern, exc,
                )
                self._reset_re = _RESET_NAME_RE
        else:
            self._reset_re = _RESET_NAME_RE

        # Optional positive-match for clocks. When set, we require the signal
        # name to match this regex AND not match the reset regex to count as
        # a clock. When None (default), preserve legacy behaviour: any signal
        # not matching the reset regex is treated as a clock.
        self._clock_re: Optional[_re.Pattern] = None
        if clock_signal_pattern:
            try:
                self._clock_re = _re.compile(clock_signal_pattern, _re.IGNORECASE)
            except _re.error as exc:
                logger.warning(
                    "invalid clock_signal_pattern %r (%s); ignoring",
                    clock_signal_pattern, exc,
                )
                self._clock_re = None
        # Extra include directories searched for `\`include` directives, in
        # addition to any `+incdir+` lines parsed from the filelist.
        self._extra_incdirs: List[str] = list(incdirs or [])
        # Predefined macros, in pyslang `NAME` or `NAME=VALUE` form. Bare
        # names are normalised to `NAME=1` to match common tool conventions
        # (e.g. a feature gate like `ENABLE_DEBUG`).
        self._defines: List[str] = []
        for d in defines or []:
            self._defines.append(d if "=" in d else f"{d}=1")
        # Held on the instance so pyslang's C++ side keeps its source
        # buffers alive for the duration of the compilation walk.
        self._source_manager: Optional[object] = None
        self._options_bag: Optional[object] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> List[Triple]:
        """Return the slang triple set (back-compat with the legacy API)."""
        return self.analyze_full().triples

    def analyze_full(self) -> ExtractionResult:
        """Elaborate the design and return all hierarchy + connectivity triples."""
        file_paths, include_dirs = self.parse_filelist(self._filelist_path)
        if not file_paths:
            logger.warning("No SV files found in filelist: %s", self._filelist_path)
            return ExtractionResult()

        try:
            compilation = self._build_compilation(file_paths, include_dirs)
        except Exception as exc:
            logger.warning("pyslang compilation failed: %s", exc)
            return ExtractionResult()

        try:
            triples, entities = self._walk_hierarchy(compilation)
        except Exception as exc:
            logger.warning("pyslang hierarchy walk failed: %s", exc)
            return ExtractionResult()

        logger.info(
            "slang analysis: produced %d hierarchy/connectivity triples, "
            "%d clock/reset domain entities",
            len(triples), len(entities),
        )
        return ExtractionResult(entities=entities, triples=triples)

    # ------------------------------------------------------------------
    # Filelist parsing (kept identical to legacy behaviour)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_filelist(
        filelist_path: str, _visited: Optional[Set[str]] = None,
    ) -> Tuple[List[str], List[str]]:
        if _visited is None:
            _visited = set()

        real_path = str(Path(filelist_path).resolve())
        if real_path in _visited:
            logger.warning("Circular filelist reference: %s", filelist_path)
            return [], []
        _visited.add(real_path)

        base_dir = Path(filelist_path).parent
        file_paths: List[str] = []
        include_dirs: List[str] = []

        try:
            with open(filelist_path, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line or line.startswith("//"):
                        continue
                    if line.startswith("+incdir+"):
                        include_dirs.append(
                            str((base_dir / line[len("+incdir+"):]).resolve())
                        )
                    elif line.startswith("-f "):
                        sub_path = str((base_dir / line[3:].strip()).resolve())
                        sub_files, sub_incs = SlangHierarchyAnalyzer.parse_filelist(
                            sub_path, _visited
                        )
                        file_paths.extend(sub_files)
                        include_dirs.extend(sub_incs)
                    else:
                        file_paths.append(str((base_dir / line).resolve()))
        except FileNotFoundError:
            logger.warning("Filelist not found: %s", filelist_path)

        return file_paths, include_dirs

    # ------------------------------------------------------------------
    # Compilation + hierarchy walk
    # ------------------------------------------------------------------

    def _build_compilation(
        self, file_paths: List[str], include_dirs: List[str]
    ) -> "_ps.Compilation":
        comp = _ps.Compilation()

        # Combine filelist `+incdir+` paths with constructor-supplied incdirs.
        all_incdirs = list(include_dirs) + list(self._extra_incdirs)

        # Build a shared SourceManager + options Bag so every syntax tree
        # sees the same include search path and macro predefines. Stash on
        # ``self`` to keep the underlying C++ buffers alive for the entire
        # hierarchy walk that follows.
        source_manager: Optional[object] = None
        options_bag: Optional[object] = None
        if all_incdirs or self._defines:
            try:
                pp_opts = _ps.PreprocessorOptions()
                if all_incdirs:
                    pp_opts.additionalIncludePaths = list(all_incdirs)
                if self._defines:
                    pp_opts.predefines = list(self._defines)
                options_bag = _ps.Bag()
                options_bag.preprocessorOptions = pp_opts
                source_manager = _ps.SourceManager()
                # Register include search paths on the SourceManager too so
                # `readHeader` can resolve `\`include` targets at lookup time.
                for inc in all_incdirs:
                    try:
                        source_manager.addUserDirectories(inc)
                    except Exception:
                        # Older pyslang builds may not expose this; the
                        # PreprocessorOptions paths are usually sufficient.
                        pass
            except Exception as exc:
                logger.warning(
                    "pyslang preprocessor options unavailable (%s); "
                    "falling back to defaults", exc,
                )
                source_manager = None
                options_bag = None

        for fp in file_paths:
            tree = None
            if source_manager is not None and options_bag is not None:
                try:
                    tree = _ps.SyntaxTree.fromFile(fp, source_manager, options_bag)
                except Exception:
                    tree = None
            if tree is None:
                try:
                    tree = _ps.SyntaxTree.fromFile(fp)
                except Exception:
                    # Fallback for older pyslang variants without fromFile
                    tree = _ps.SyntaxTree.fromText(Path(fp).read_text())
            comp.addSyntaxTree(tree)
        # Retain options + source manager so their C++ resources outlive
        # the compilation walk.
        self._source_manager = source_manager
        self._options_bag = options_bag
        return comp

    def _walk_hierarchy(
        self, compilation: "_ps.Compilation"
    ) -> Tuple[List[Triple], List[Entity]]:
        root = compilation.getRoot()
        triples: List[Triple] = []
        seen_definitions: Set[str] = set()
        # Definition kind per unique module name encountered during the walk.
        # Used to emit a properly-typed entity per def (RTL_Module / Interface
        # / Program). Without this, prim_*/tlul_* sub-instances reachable from
        # the top get auto-created by add_edge as type='concept' and become
        # invisible to RTL_Module-filtered queries (reachability, layout).
        definition_kinds: dict[str, str] = {}
        # Clock/reset domain accumulators. Maps signal name -> sources set.
        clock_domains: dict[str, set[str]] = {}
        reset_domains: dict[str, set[str]] = {}
        # Edges already emitted, keyed by (module_def, signal_name, predicate)
        # to dedup repeated always_ff blocks in the same module.
        seen_clock_edges: Set[Tuple[str, str]] = set()
        seen_reset_edges: Set[Tuple[str, str]] = set()
        # Assertion entities accumulated across modules. Keyed by canonical
        # entity name (`{module}.{label_or_synthetic}`) so a module reused
        # across instances doesn't duplicate the entity. Per-definition
        # counter for synthetic anonymous-assertion names lives in
        # ``seen_assertion_defs`` so we only walk a definition once.
        assertion_entities: dict[str, Entity] = {}
        seen_assertion_defs: Set[str] = set()
        # FSM entities + per-state entities accumulated across modules.
        # Walk each module definition only once (``seen_fsm_defs``) — FSMs
        # are a property of the definition, not the instantiation.
        fsm_entities: dict[str, Entity] = {}
        fsm_state_entities: dict[str, Entity] = {}
        seen_fsm_defs: Set[str] = set()
        # Dataflow walker is per-definition (intra-module reads).
        seen_dataflow_defs: Set[str] = set()
        # Covergroup walker is per-definition. Covergroup_SV / Coverpoint /
        # CoverBin / CoverCross entities accumulate here, deduped by canonical
        # entity name across repeat instantiations of the same module.
        cov_entities: dict[str, Entity] = {}
        seen_cov_defs: Set[str] = set()
        # Port entities accumulated across module definitions so that
        # ``port_direction`` is preserved on the canonical Port node. Keyed
        # by qualified name (``<module>.<port>``) so a module reused across
        # instances doesn't duplicate the entity.
        port_entities: dict[str, Entity] = {}

        def emit(
            subject: str,
            predicate: str,
            obj: str,
            evidence_span: str = "",
            lhs_slice: Optional[str] = None,
            rhs_slice: Optional[str] = None,
            attributes: Optional[dict] = None,
            layer: Optional[str] = None,
        ) -> None:
            triples.append(Triple(
                subject=subject,
                predicate=predicate,
                object=obj,
                source=SV_CONNECTIVITY_SOURCE,
                extractor_source="slang",
                evidence_span=evidence_span,
                lhs_slice=lhs_slice,
                rhs_slice=rhs_slice,
                layer=layer,
                attributes=dict(attributes) if attributes else {},
            ))

        # The top-level filter: the top module the user requested, else all tops.
        tops = list(root.topInstances)
        if self._top_module:
            tops = [t for t in tops if t.name == self._top_module] or tops

        # Interfaces elaborated at $root are not in topInstances (pyslang
        # only lists module tops there). Walk root-level SymbolKind.Instance
        # nodes whose *definition* name matches the requested top — this
        # surfaces stand-alone interface compilations (e.g. aes_cov_if).
        if self._top_module and not tops:
            for item in root:
                if getattr(item, "kind", None) == _ps.SymbolKind.Instance:
                    try:
                        def_nm = item.definition.name
                    except Exception:
                        def_nm = ""
                    if def_nm == self._top_module:
                        tops.append(item)
                        break

        # Walk each top, tracking the parent-instance stack for part_of.
        for top in tops:
            self._walk_instance(
                inst=top,
                parent_hier=None,
                parent_def_name=None,
                seen_definitions=seen_definitions,
                emit=emit,
                clock_domains=clock_domains,
                reset_domains=reset_domains,
                seen_clock_edges=seen_clock_edges,
                seen_reset_edges=seen_reset_edges,
                assertion_entities=assertion_entities,
                seen_assertion_defs=seen_assertion_defs,
                fsm_entities=fsm_entities,
                fsm_state_entities=fsm_state_entities,
                seen_fsm_defs=seen_fsm_defs,
                seen_dataflow_defs=seen_dataflow_defs,
                cov_entities=cov_entities,
                seen_cov_defs=seen_cov_defs,
                definition_kinds=definition_kinds,
                port_entities=port_entities,
            )

        # Emit bound_into edges from every `bind` directive in the design.
        # Walked at compilation scope (independent of the top-instance tree)
        # because slang's elaborated symbol tree does not flag injected
        # children as bind-sourced — and unresolvable bind sources are
        # silently dropped from elaboration but must still surface as audit
        # signals.
        self._emit_bind_directive_edges(compilation, emit)

        # Emit one entity per distinct clock/reset signal name.
        entities: List[Entity] = []
        for name, sources in clock_domains.items():
            entities.append(Entity(
                name=name,
                type="ClockDomain",
                sources=sorted(sources),
                extractor_source=["slang"],
            ))
        for name, sources in reset_domains.items():
            entities.append(Entity(
                name=name,
                type="ResetDomain",
                sources=sorted(sources),
                extractor_source=["slang"],
            ))
        # Emit one entity per assertion (already deduped by name in the dict).
        entities.extend(assertion_entities.values())
        # FSM + FSM_State entities (deduped by name).
        entities.extend(fsm_entities.values())
        entities.extend(fsm_state_entities.values())
        # Covergroup_SV / Coverpoint / CoverBin / CoverCross entities.
        entities.extend(cov_entities.values())
        # Port entities with port_direction (so the attribute round-trips
        # through the backend rather than being lost on auto-creation).
        entities.extend(port_entities.values())

        # Typed entity per unique definition encountered during the walk.
        # Without this, modules slang elaborates but parser_extractor never
        # scans (e.g. prim_*, tlul_* under prim/rtl/) get auto-created by
        # add_edge as type='concept' — invisible to RTL_Module-typed queries.
        # Closes the top-down hierarchy tracing path: every node reachable
        # from the top via instantiates is now a properly-typed entity.
        for def_name in sorted(seen_definitions):
            entities.append(Entity(
                name=def_name,
                type=definition_kinds.get(def_name, "RTL_Module"),
                extractor_source=["slang"],
                layer=SV_CONNECTIVITY_SOURCE,
            ))

        # Also emit RTL_Module entities for instantiates targets whose body
        # slang never walked (because the source isn't on the filelist —
        # the prim_*/tlul_* case in OpenTitan AES). These nodes appear only
        # as the OBJECT of instantiates triples and would otherwise default
        # to type='concept', breaking RTL_Module-typed reachability queries.
        # We default to RTL_Module since we have no way to detect Interface
        # for an un-elaborated definition.
        instantiated_names: Set[str] = set()
        for t in triples:
            if t.predicate == "instantiates":
                instantiated_names.add(t.object)
        for name in sorted(instantiated_names - seen_definitions):
            entities.append(Entity(
                name=name,
                type="RTL_Module",
                extractor_source=["slang"],
                layer=SV_CONNECTIVITY_SOURCE,
            ))

        return triples, entities

    def _walk_instance(
        self,
        inst: "_ps.InstanceSymbol",
        parent_hier: Optional[str],
        parent_def_name: Optional[str],
        seen_definitions: Set[str],
        emit,
        clock_domains: dict,
        reset_domains: dict,
        seen_clock_edges: Set[Tuple[str, str]],
        seen_reset_edges: Set[Tuple[str, str]],
        assertion_entities: dict,
        seen_assertion_defs: Set[str],
        fsm_entities: dict,
        fsm_state_entities: dict,
        seen_fsm_defs: Set[str],
        seen_dataflow_defs: Set[str],
        cov_entities: dict,
        seen_cov_defs: Set[str],
        definition_kinds: Optional[dict] = None,
        port_entities: Optional[dict] = None,
    ) -> None:
        """Recursively walk an elaborated InstanceSymbol."""
        if definition_kinds is None:
            definition_kinds = {}
        if port_entities is None:
            port_entities = {}
        def_name = inst.definition.name
        hier_path = self._hier_path(inst)

        # 1) instance_of: hier_path -> definition module name
        emit(hier_path, "instance_of", def_name)

        # 2) part_of: hier_path -> parent_hier (skip for top instances)
        if parent_hier is not None:
            emit(hier_path, "part_of", parent_hier)

        # 3) instantiates: parent_def -> def (definition-level edge)
        if parent_def_name is not None and parent_def_name != def_name:
            emit(parent_def_name, "instantiates", def_name)

        # 4) contains: definition-level edges (one per unique definition)
        if def_name not in seen_definitions:
            seen_definitions.add(def_name)
            self._emit_contains_for_definition(
                inst, def_name, emit, port_entities,
            )
            # Record definition kind so we can emit a properly-typed entity
            # post-walk. ``inst.definition.definitionKind`` is a pyslang enum;
            # str(...) yields ``DefinitionKind.Module`` / ``.Interface`` /
            # ``.Program``. Default to RTL_Module if the attribute is missing
            # on older pyslang builds.
            kind_str = ""
            try:
                kind_str = str(inst.definition.definitionKind)
            except Exception:
                kind_str = ""
            if kind_str.endswith("Interface"):
                definition_kinds[def_name] = "Interface"
            elif kind_str.endswith("Program"):
                definition_kinds[def_name] = "Program"
            else:
                definition_kinds[def_name] = "RTL_Module"

        # 5) port connections — connects_to (back-compat) + directional drives edges
        self._emit_port_connections(inst, hier_path, emit)

        # 5b) parameter value bindings: binds_parameter edges
        self._emit_parameter_bindings(inst, hier_path, def_name, emit)

        # 5c) clocked_by / reset_by edges from always_ff sensitivity lists.
        # These are properties of the module *definition*, not the instance —
        # only emit per (def_name, signal) pair to avoid duplicates across
        # repeated instantiations of the same module.
        self._emit_clock_reset_edges(
            inst, def_name, emit,
            clock_domains, reset_domains,
            seen_clock_edges, seen_reset_edges,
        )

        # 5d) Concurrent / immediate assertion extraction. Like clock/reset
        # edges, these are properties of the module *definition*, so we only
        # walk each unique definition once (keyed in ``seen_assertion_defs``).
        if def_name not in seen_assertion_defs:
            seen_assertion_defs.add(def_name)
            self._emit_assertion_edges(
                inst, def_name, emit, assertion_entities, clock_domains,
            )

        # 5e) FSM extraction. Like assertions, FSMs are properties of the
        # module *definition*, walked once per unique def_name.
        if def_name not in seen_fsm_defs:
            seen_fsm_defs.add(def_name)
            self._emit_fsm_edges(
                inst, def_name, emit, fsm_entities, fsm_state_entities,
            )

        # 5f) Intra-module signal-level dataflow (reads edges).
        if def_name not in seen_dataflow_defs:
            seen_dataflow_defs.add(def_name)
            self._emit_dataflow_edges(inst, def_name, emit)

        # 5g) Covergroup_SV / Coverpoint / CoverBin / CoverCross extraction.
        # Like assertions/FSMs, covergroups belong to the module *definition*.
        if def_name not in seen_cov_defs:
            seen_cov_defs.add(def_name)
            self._emit_covergroup_edges(inst, def_name, emit, cov_entities)

        # 6) recurse into nested instances
        body = inst.body
        for member in body:
            if member.kind == _ps.SymbolKind.Instance:
                self._walk_instance(
                    inst=member,
                    parent_hier=hier_path,
                    parent_def_name=def_name,
                    seen_definitions=seen_definitions,
                    emit=emit,
                    clock_domains=clock_domains,
                    reset_domains=reset_domains,
                    seen_clock_edges=seen_clock_edges,
                    seen_reset_edges=seen_reset_edges,
                    assertion_entities=assertion_entities,
                    seen_assertion_defs=seen_assertion_defs,
                    fsm_entities=fsm_entities,
                    fsm_state_entities=fsm_state_entities,
                    seen_fsm_defs=seen_fsm_defs,
                    seen_dataflow_defs=seen_dataflow_defs,
                    cov_entities=cov_entities,
                    seen_cov_defs=seen_cov_defs,
                    definition_kinds=definition_kinds,
                    port_entities=port_entities,
                )

    @staticmethod
    def _hier_path(inst: "_ps.InstanceSymbol") -> str:
        """Return the elaborated hierarchical path for an instance."""
        path = getattr(inst, "hierarchicalPath", "") or ""
        # Slang sometimes emits trailing whitespace (e.g. "$root ").
        return path.strip()

    def _emit_contains_for_definition(
        self,
        inst: "_ps.InstanceSymbol",
        def_name: str,
        emit,
        port_entities: dict,
    ) -> None:
        """Emit ``contains`` edges from a module definition to its members.

        Also accumulates Port entities (with normalized ``port_direction``)
        into ``port_entities`` so the caller can upsert them as typed nodes.
        Without this, Port nodes would be auto-created by ``add_edge`` as
        bare ``concept`` placeholders missing the direction attribute.
        """
        body = inst.body
        seen_names: Set[str] = set()
        for member in body:
            kind = member.kind
            # pyslang occasionally raises UnicodeDecodeError on synthetic
            # symbols generated by macro expansion (e.g. assertion labels);
            # skip those rather than aborting the whole hierarchy walk.
            try:
                name = getattr(member, "name", "")
            except UnicodeDecodeError:
                continue
            if not name or name in seen_names:
                continue
            # Filter to entity-bearing kinds: ports, nets/variables, parameters.
            if kind not in (
                _ps.SymbolKind.Port,
                _ps.SymbolKind.Net,
                _ps.SymbolKind.Variable,
                _ps.SymbolKind.Parameter,
                _ps.SymbolKind.TypeParameter,
            ):
                continue
            seen_names.add(name)
            qualified = f"{def_name}.{name}"
            emit(def_name, "contains", qualified)

            # Capture Port direction. ``ArgumentDirection`` enum values
            # stringify as ``ArgumentDirection.In`` / ``.Out`` / ``.InOut`` /
            # ``.Ref``. ``Ref`` and unknown values leave port_direction unset
            # (None) — we don't fabricate a direction we can't classify.
            if kind == _ps.SymbolKind.Port and qualified not in port_entities:
                direction_value: Optional[str] = None
                try:
                    raw = getattr(member, "direction", None)
                    if raw is not None:
                        s = str(raw)
                        if s.endswith(".In") or s == "In":
                            direction_value = "input"
                        elif s.endswith(".Out") or s == "Out":
                            direction_value = "output"
                        elif s.endswith(".InOut") or s == "InOut":
                            direction_value = "inout"
                        # Ref / unknown -> leave None.
                except Exception:
                    direction_value = None
                port_entities[qualified] = Entity(
                    name=qualified,
                    type="Port",
                    extractor_source=["slang"],
                    layer=SV_CONNECTIVITY_SOURCE,
                    port_direction=direction_value,
                )

    def _emit_port_connections(
        self,
        inst: "_ps.InstanceSymbol",
        hier_path: str,
        emit,
    ) -> None:
        """Walk port connections and emit ``connects_to`` edges with hier paths."""
        try:
            port_conns = list(inst.portConnections)
        except Exception:
            return

        for pc in port_conns:
            port = getattr(pc, "port", None)
            expr = getattr(pc, "expression", None)
            if port is None or expr is None:
                continue
            port_name = getattr(port, "name", "")
            if not port_name:
                continue
            port_node = f"{hier_path}.{port_name}"

            leaves = self._collect_named_value_paths(expr)
            direction = getattr(port, "direction", None)
            dir_str = str(direction) if direction is not None else ""
            # ArgumentDirection.{In,Out,InOut,Ref}
            is_input = dir_str.endswith(".In") or dir_str == "In"
            is_output = dir_str.endswith(".Out") or dir_str == "Out"
            is_inout = dir_str.endswith(".InOut") or dir_str == "InOut"

            for leaf in leaves:
                if not leaf or leaf == port_node:
                    continue
                # NetworkX DiGraph collapses parallel edges into one record
                # keyed by (subject, object), so emitting both `drives` and
                # the legacy `connects_to` between the same pair shadowed
                # whichever came second. Keep only the directional edge.
                if is_input:
                    emit(leaf, "drives", port_node)
                elif is_output:
                    emit(port_node, "drives", leaf)
                elif is_inout:
                    emit(port_node, "drives", leaf)
                    emit(leaf, "drives", port_node)
                else:
                    # Unknown / Ref: default to instance-port-as-source.
                    emit(port_node, "drives", leaf)

                # ----------------------------------------------------------
                # V2 unification (Wave 2 / track E):
                # Dual-emit `data_flows` for the port-instance binding so a
                # BFS over `data_flows` traverses across module boundaries
                # without falling back to legacy `drives` / `connects_to`.
                # `flow_kind` records which side of the boundary this edge
                # represents:
                #   port_in  : parent net  → child input port
                #   port_out : child output port → parent net
                # `inout` ports emit both directions. All `data_flows`
                # triples carry layer="slang" per the v2 schema doc.
                # ----------------------------------------------------------
                if is_input:
                    emit(
                        leaf, "data_flows", port_node,
                        attributes={"flow_kind": "port_in"},
                        layer="slang",
                    )
                elif is_output:
                    emit(
                        port_node, "data_flows", leaf,
                        attributes={"flow_kind": "port_out"},
                        layer="slang",
                    )
                elif is_inout:
                    emit(
                        leaf, "data_flows", port_node,
                        attributes={"flow_kind": "port_in"},
                        layer="slang",
                    )
                    emit(
                        port_node, "data_flows", leaf,
                        attributes={"flow_kind": "port_out"},
                        layer="slang",
                    )
                else:
                    # Unknown direction: fall back to instance-port-as-source
                    # mirroring the legacy `drives` policy. Tag as port_out
                    # since that matches the emitted direction.
                    emit(
                        port_node, "data_flows", leaf,
                        attributes={"flow_kind": "port_out"},
                        layer="slang",
                    )

    def _emit_parameter_bindings(
        self,
        inst: "_ps.InstanceSymbol",
        hier_path: str,
        def_name: str,
        emit,
    ) -> None:
        """Emit ``binds_parameter`` edges from instance hier path to parameter entity.

        Each elaborated ``ParameterSymbol`` on the instance body carries a
        resolved ``.value`` (a ``slang.ConstantValue``). We stringify it and
        place ``"<name>=<value>"`` in the edge's ``evidence_span``. Edges are
        emitted for both overridden and default-value parameters so callers
        can answer "what is X for this instance?" uniformly.
        """
        try:
            body = inst.body
        except Exception:
            return
        for member in body:
            kind = getattr(member, "kind", None)
            if kind != _ps.SymbolKind.Parameter:
                continue
            name = getattr(member, "name", "")
            if not name:
                continue
            value = getattr(member, "value", None)
            try:
                value_str = str(value) if value is not None else ""
            except Exception:
                value_str = ""
            evidence = f"{name}={value_str}"
            param_entity = f"{def_name}.{name}"
            emit(hier_path, "binds_parameter", param_entity, evidence_span=evidence)

    def _emit_clock_reset_edges(
        self,
        inst: "_ps.InstanceSymbol",
        def_name: str,
        emit,
        clock_domains: dict,
        reset_domains: dict,
        seen_clock_edges: Set[Tuple[str, str]],
        seen_reset_edges: Set[Tuple[str, str]],
    ) -> None:
        """Walk always_ff procedural blocks and emit clocked_by / reset_by edges.

        Uses pyslang's elaborated ``ProceduralBlockSymbol`` (procedureKind ==
        ``AlwaysFF``). Inspects the body's ``TimingControl`` (``EventList`` for
        multi-event sensitivity, or a bare ``SignalEvent`` for single-event).
        Each ``SignalEvent`` carries an ``EdgeKind`` (PosEdge/NegEdge/AnyEdge)
        and a ``NamedValue`` expression resolving to the clock/reset symbol.

        A signal is classified as a reset (vs. clock) by name heuristic:
        ``rst*`` / ``*reset*`` / ``por*``. This is necessary because slang
        does not encode "reset-ness" structurally — both clocks and async
        resets appear identically in the sensitivity list.

        Multi-clock always_ffs (e.g. ``@(posedge clk1 or posedge clk2)``,
        used by clock muxes) emit one ``clocked_by`` edge per non-reset
        signal so the module is correctly tagged as living in both domains.
        """
        try:
            body = inst.body
        except Exception:
            return

        source_path = ""
        try:
            sr = getattr(inst.definition, "sourceRange", None)
            buf = getattr(getattr(sr, "start", None), "buffer", None)
            if buf is not None:
                source_path = str(getattr(buf, "name", "") or "")
        except Exception:
            source_path = ""

        for member in body:
            if getattr(member, "kind", None) != _ps.SymbolKind.ProceduralBlock:
                continue
            proc_kind = getattr(member, "procedureKind", None)
            # Sequential blocks: AlwaysFF (and arguably plain Always with
            # edge-sensitive timing, but stick to AlwaysFF — the safer signal).
            if str(proc_kind) != "ProceduralBlockKind.AlwaysFF":
                continue

            stmt = getattr(member, "body", None)
            if stmt is None:
                continue
            timing = getattr(stmt, "timing", None)
            if timing is None:
                continue

            for ev in self._iter_signal_events(timing):
                edge = getattr(ev, "edge", None)
                edge_str = str(edge) if edge is not None else ""
                # Only consider edge-sensitive entries (PosEdge / NegEdge /
                # BothEdges). A bare level reference shouldn't really appear
                # in always_ff but skip if so.
                if not (
                    "PosEdge" in edge_str
                    or "NegEdge" in edge_str
                    or "BothEdges" in edge_str
                ):
                    continue
                expr = getattr(ev, "expr", None)
                if expr is None:
                    continue
                sym = getattr(expr, "symbol", None)
                if sym is None:
                    continue
                sig_name = getattr(sym, "name", "") or ""
                if not sig_name:
                    continue

                is_reset = bool(self._reset_re.search(sig_name))
                if self._clock_re is not None:
                    is_clock = bool(self._clock_re.search(sig_name)) and not is_reset
                else:
                    is_clock = not is_reset
                if is_reset:
                    # ResetDomain
                    if source_path:
                        reset_domains.setdefault(sig_name, set()).add(source_path)
                    else:
                        reset_domains.setdefault(sig_name, set())
                    key = (def_name, sig_name)
                    if key not in seen_reset_edges:
                        seen_reset_edges.add(key)
                        emit(def_name, "reset_by", sig_name)
                elif is_clock:
                    # ClockDomain
                    if source_path:
                        clock_domains.setdefault(sig_name, set()).add(source_path)
                    else:
                        clock_domains.setdefault(sig_name, set())
                    key = (def_name, sig_name)
                    if key not in seen_clock_edges:
                        seen_clock_edges.add(key)
                        emit(def_name, "clocked_by", sig_name)

    def _emit_assertion_edges(
        self,
        inst: "_ps.InstanceSymbol",
        def_name: str,
        emit,
        assertion_entities: dict,
        clock_domains: dict,
    ) -> None:
        """Emit SVA_Assertion entities + has_assertion / references_signal edges.

        Uses the **elaborated symbol tree** for assertion discovery (not a
        syntax-tree fallback). pyslang surfaces concurrent assertions as
        ``ProceduralBlock`` symbols whose ``body`` statement is
        ``StatementKind.ConcurrentAssertion`` and whose ``assertionKind`` is
        one of ``Assert``/``Assume``/``Cover``/``Restrict``. Immediate
        assertions appear under ``StatementKind.ImmediateAssertion`` (we
        capture those too for completeness).

        **Labels**: a labeled assertion (``my_label: assert property (...)``)
        elaborates as a ``ProceduralBlock`` whose body is a
        ``StatementKind.Block`` (with ``blockSymbol.name == "my_label"``)
        containing the real ``ConcurrentAssertion``. We descend through the
        Block to find the assertion and pull the label off ``blockSymbol``.
        Slang also surfaces a sibling empty ``StatementBlock`` for the same
        label; we ignore it (the elaborated path inside the ProceduralBlock
        is the authoritative source).
        Anonymous assertions get a synthetic ``{kind}_{counter}`` name.

        **Referenced signals**: the assertion's ``propertySpec`` does not
        expose a uniform ``visit`` API across all sub-expression node types
        in this pyslang version, so we extract identifiers from the
        property's syntax-text representation (``str(spec.syntax)``) and
        intersect with the module's port/signal/parameter names plus the
        running clock-domain registry. This is a deterministic intersection
        — no false positives from keywords because we only resolve to
        identifiers we already know exist.
        """
        try:
            body = inst.body
        except Exception:
            return

        # Build the lookup table: simple name -> entity name. Ports and
        # signals get a ``{def_name}.{name}`` qualifier; clocks resolve to
        # the bare ClockDomain entity name (no module prefix).
        # Generate blocks (``if (param) begin : gen_*``) are common containers
        # for parameter-gated assertions in OpenTitan; flatten into them when
        # collecting both signals and ProceduralBlocks so we don't miss
        # assertions hidden one level below the module body.
        def _walk_members(scope):
            try:
                items = list(scope)
            except TypeError:
                return
            for m in items:
                yield m
                mk = getattr(m, "kind", None)
                if mk == _ps.SymbolKind.GenerateBlock:
                    yield from _walk_members(m)
                elif mk == _ps.SymbolKind.GenerateBlockArray:
                    yield from _walk_members(m)

        sig_entity: dict[str, str] = {}
        for member in _walk_members(body):
            kind = getattr(member, "kind", None)
            name = getattr(member, "name", "")
            if not name:
                continue
            if kind in (
                _ps.SymbolKind.Port,
                _ps.SymbolKind.Net,
                _ps.SymbolKind.Variable,
                _ps.SymbolKind.Parameter,
            ):
                sig_entity[name] = f"{def_name}.{name}"

        anon_counters: dict[str, int] = {}
        for member in _walk_members(body):
            mkind = getattr(member, "kind", None)
            if mkind != _ps.SymbolKind.ProceduralBlock:
                continue

            stmt = getattr(member, "body", None)
            if stmt is None:
                continue

            # Unwrap a one-statement Block (slang's elaboration of a
            # labeled assertion). Pull the label off ``blockSymbol``.
            label: Optional[str] = None
            stmt_kind = str(getattr(stmt, "kind", ""))
            if stmt_kind.endswith("Block"):
                bs = getattr(stmt, "blockSymbol", None)
                if bs is not None:
                    bn = getattr(bs, "name", "") or ""
                    if bn:
                        label = bn
                inner = getattr(stmt, "body", None)
                if inner is not None:
                    stmt = inner
                    stmt_kind = str(getattr(stmt, "kind", ""))

            is_concurrent = stmt_kind.endswith("ConcurrentAssertion")
            is_immediate = stmt_kind.endswith("ImmediateAssertion")
            if not (is_concurrent or is_immediate):
                continue

            # Determine assertion kind tag (assert / assume / cover / restrict).
            akind_raw = getattr(stmt, "assertionKind", None)
            akind_str = str(akind_raw) if akind_raw is not None else ""
            # Slang prints e.g. ``AssertionKind.Assert`` /
            # ``AssertionKind.CoverProperty`` / ``AssertionKind.CoverSequence``;
            # normalize to one of {assert, assume, cover, restrict}.
            if "." in akind_str:
                tail = akind_str.rsplit(".", 1)[1].lower()
            else:
                tail = akind_str.lower() or "assert"
            if tail.startswith("cover"):
                akind = "cover"
            elif tail.startswith("assume"):
                akind = "assume"
            elif tail.startswith("restrict"):
                akind = "restrict"
            else:
                akind = "assert"

            # Resolve label or synthesize a counter-based name.
            if label:
                ent_name = f"{def_name}.{label}"
            else:
                idx = anon_counters.get(akind, 0)
                anon_counters[akind] = idx + 1
                ent_name = f"{def_name}.{akind}_{idx}"

            # Extract property text. Use the syntax representation of the
            # ConcurrentAssertion's propertySpec (or the ImmediateAssertion's
            # ``cond`` expression) for the evidence span.
            expr_text = ""
            try:
                if is_concurrent:
                    spec = getattr(stmt, "propertySpec", None)
                    if spec is not None:
                        syn = getattr(spec, "syntax", None)
                        if syn is not None:
                            expr_text = str(syn).strip()
                else:
                    cond = getattr(stmt, "cond", None)
                    if cond is not None:
                        syn = getattr(cond, "syntax", None)
                        if syn is not None:
                            expr_text = str(syn).strip()
            except Exception:
                expr_text = ""

            # Encode kind in evidence_span so callers (and downstream tests)
            # can recover the assert/assume/cover/restrict distinction. The
            # Entity itself stays a single ``SVA_Assertion`` type per schema.
            evidence = f"kind={akind} expr={expr_text}" if expr_text else f"kind={akind}"

            if ent_name not in assertion_entities:
                assertion_entities[ent_name] = Entity(
                    name=ent_name,
                    type="SVA_Assertion",
                    extractor_source=["slang"],
                    raw_mentions=[],
                    current_summary=evidence,
                )

            emit(def_name, "has_assertion", ent_name, evidence_span=f"kind={akind}")

            # Resolve referenced signals by identifier-intersection on the
            # property's syntax text. Dedupe per-(assertion, target) so the
            # NetworkX-DiGraph parallel-edge collapse never silently drops
            # a real predicate.
            if expr_text:
                # First pull clock identifiers out of any ``@(posedge X)``
                # or ``@(negedge X)`` timing events — those resolve to
                # ClockDomain entities (no module prefix), matching the
                # ``clocked_by`` edge convention.
                clk_idents = set(_re.findall(
                    r"@\s*\(\s*(?:posedge|negedge|edge)\s+([A-Za-z_][A-Za-z0-9_]*)",
                    expr_text,
                ))
                for ck in clk_idents:
                    # Surface the clock as a ClockDomain entity, lazily.
                    clock_domains.setdefault(ck, set())

                idents = set(_IDENT_RE.findall(expr_text))
                seen_refs: Set[str] = set()
                for ident in idents:
                    target: Optional[str] = None
                    if ident in clk_idents:
                        # Prefer ClockDomain mapping for any signal that
                        # appears in a timing event of *this* assertion.
                        target = ident
                    elif ident in sig_entity:
                        target = sig_entity[ident]
                    elif ident in clock_domains:
                        target = ident
                    if target is None or target in seen_refs:
                        continue
                    seen_refs.add(target)
                    emit(ent_name, "references_signal", target)

    def _emit_fsm_edges(
        self,
        inst: "_ps.InstanceSymbol",
        def_name: str,
        emit,
        fsm_entities: dict,
        fsm_state_entities: dict,
    ) -> None:
        """Emit FSM, FSM_State entities + has_fsm/has_state/transitions_to edges.

        Detection strategy uses pyslang's elaborated symbol tree:

        1. Walk the module body for ``SymbolKind.TypeAlias`` whose target type
           reports ``isEnum=True``. Treat that enum as a candidate FSM type.
           (Inline enum-typed Variables — no typedef — are also accepted by
           checking ``Variable.type.isEnum`` and recovering the enum
           definition through ``canonicalType``.)
        2. Identify state-register variables: ``SymbolKind.Variable`` whose
           type's canonical form is one of the candidate enum types.
        3. **Choosing cs vs ns** (when the module declares both): the FSM
           entity is the variable that appears as the LHS of a non-blocking
           assignment (``<=``) inside an ``always_ff`` procedural block —
           that's the registered state, conventionally named ``cs``/``state_q``.
           If no NBA targets any of the state-typed variables, fall back to
           the first-declared state variable. We emit ONE FSM per (module,
           enum-type) pair to avoid duplicating the same machine for ``cs``
           and ``ns``.
        4. Transitions: walk procedural blocks for ``StatementKind.Case``
           whose selector is one of the state-typed variables. For each arm,
           collect ``(label_enum_value, rhs_enum_value)`` pairs from any
           ``Assignment`` whose LHS is a state-typed Variable and RHS resolves
           via ``getSymbolReference()`` (or the ``.symbol`` attribute) to an
           ``EnumValue``. Dedupe by ``(src, dst)`` — multiple case arms with
           the same target are folded into one edge with concatenated
           condition tags in ``evidence_span`` (the NetworkX backend
           collapses parallel edges between the same pair, so we can't emit
           two ``transitions_to`` between the same pair).
        """
        try:
            body = inst.body
        except Exception:
            return

        # ---- Step 1+2: discover enum types and the variables typed by them.
        # Map enum type id() -> simple type name (state_e). Each candidate
        # enum is a per-module FSM type; multiple variables sharing the same
        # enum form one FSM.
        enum_types: dict[int, "_ps.Type"] = {}
        # name -> EnumValue symbol for each member (used by transition LHS/RHS
        # lookup later).
        enum_members: dict[int, list] = {}

        def _record_enum(t):
            try:
                if t is None or not getattr(t, "isEnum", False):
                    return
                eid = id(t)
                if eid in enum_types:
                    return
                enum_types[eid] = t
                try:
                    enum_members[eid] = list(t)
                except Exception:
                    enum_members[eid] = []
            except Exception:
                return

        for member in body:
            mk = getattr(member, "kind", None)
            if mk == _ps.SymbolKind.TypeAlias:
                # TypeAlias.targetType is a DeclaredType; its .type is the actual Type
                try:
                    dt = getattr(member, "targetType", None)
                    actual = getattr(dt, "type", None) if dt is not None else None
                    _record_enum(actual)
                except Exception:
                    pass

        # State-typed variables. We bucket them by enum-type id so we know
        # how many variables belong to the same FSM.
        state_vars: dict[int, list] = {}
        for member in body:
            if getattr(member, "kind", None) != _ps.SymbolKind.Variable:
                continue
            try:
                vt = member.type
            except Exception:
                continue
            if vt is None:
                continue
            # The variable's type may be the alias itself; resolve to its
            # canonical (which is the EnumType). Compare on canonical id.
            ct = getattr(vt, "canonicalType", None)
            if ct is None and getattr(vt, "isEnum", False):
                ct = vt
            if ct is None:
                continue
            # Inline enum types (no typedef) won't be in enum_types yet —
            # surface them now so we still discover the FSM.
            if id(ct) not in enum_types and getattr(ct, "isEnum", False):
                _record_enum(ct)
            if id(ct) in enum_types:
                state_vars.setdefault(id(ct), []).append(member)

        if not state_vars:
            return

        # ---- Step 3: pick the state register (LHS of NBA inside always_ff).
        nba_lhs_vars: Set[str] = set()  # variable symbol names
        # Map case-statement selectors -> Variable name(s); used as a
        # secondary tiebreak AND as part of the FSM-qualification criterion
        # (enum vars only become FSMs if used as a case selector or in an
        # if-ladder condition).
        case_selector_vars: Set[str] = set()
        # Variables referenced anywhere inside an if/else-if predicate
        # (i.e. the condition expression of a ConditionalStatement). These
        # — together with case_selector_vars — are the set of enum vars
        # that we trust as "real" state-holders rather than data.
        if_condition_vars: Set[str] = set()
        # Collect all case statements + their procedural-block bodies for
        # later transition extraction.
        case_stmts: list = []
        # Conditional (if/else-if) statements collected per procedural-block,
        # used in step 5 to walk priority ladders for transitions.
        # List of (proc_kind_str, conditional_stmt).
        conditional_stmts: list = []

        # Pre-compute: a quick set of all candidate state-typed Variable
        # names so we can filter NamedValue refs in if-conditions.
        candidate_state_var_names: Set[str] = {
            v.name for vs in state_vars.values() for v in vs
        }

        def _collect_named_value_names(expr) -> List[str]:
            """Collect symbol names of NamedValue leaves under ``expr``."""
            out: list = []

            def _vis(node):
                k = getattr(node, "kind", None)
                if k is None:
                    return
                if str(k).endswith("NamedValue"):
                    sym = getattr(node, "symbol", None)
                    if sym is not None:
                        nm = getattr(sym, "name", "") or ""
                        if nm:
                            out.append(nm)

            try:
                expr.visit(_vis)
            except Exception:
                pass
            return out

        def _walk_stmts(stmt, in_alwaysff: bool, in_alwayscomb: bool,
                         in_case_arm: bool = False):
            kind_str = str(getattr(stmt, "kind", ""))
            if kind_str.endswith("ExpressionStatement"):
                e = getattr(stmt, "expr", None)
                if e is not None and str(getattr(e, "kind", "")).endswith("Assignment"):
                    if in_alwaysff and getattr(e, "isNonBlocking", False):
                        lsym = getattr(getattr(e, "left", None), "symbol", None)
                        if lsym is not None:
                            nm = getattr(lsym, "name", "")
                            if nm:
                                nba_lhs_vars.add(nm)
                return
            if kind_str.endswith("Case"):
                expr = getattr(stmt, "expr", None)
                sel = getattr(expr, "symbol", None)
                if sel is not None:
                    nm = getattr(sel, "name", "")
                    if nm:
                        case_selector_vars.add(nm)
                case_stmts.append(stmt)
                # Recurse into arms anyway (nested case is rare but possible).
                for arm in getattr(stmt, "items", []) or []:
                    inner = getattr(arm, "stmt", None)
                    if inner is not None:
                        _walk_stmts(inner, in_alwaysff, in_alwayscomb,
                                    in_case_arm=True)
                default_arm = getattr(stmt, "defaultCase", None)
                if default_arm is not None:
                    _walk_stmts(default_arm, in_alwaysff, in_alwayscomb,
                                in_case_arm=True)
                return
            if kind_str.endswith("Conditional"):
                # Capture every NamedValue referenced inside any branch
                # predicate — this is what qualifies an enum as an FSM.
                for cond in getattr(stmt, "conditions", []) or []:
                    pred = getattr(cond, "expr", None)
                    if pred is None:
                        continue
                    for nm in _collect_named_value_names(pred):
                        if nm in candidate_state_var_names:
                            if_condition_vars.add(nm)
                # Record this conditional for later priority-ladder walking
                # (only meaningful inside always_comb / always_latch, and
                # only top-level — conditionals nested inside a case arm
                # are already covered by the case-walker).
                if in_alwayscomb and not in_case_arm:
                    conditional_stmts.append(stmt)
                # Recurse into both branches. Mark them as in_case_arm to
                # suppress collecting nested conditionals — the top-level
                # ladder walker handles else-if recursion itself.
                for attr in ("ifTrue", "ifFalse"):
                    v = getattr(stmt, attr, None)
                    if v is not None and hasattr(v, "kind"):
                        _walk_stmts(v, in_alwaysff, in_alwayscomb,
                                    in_case_arm=in_case_arm or in_alwayscomb)
                return
            # Generic recursion across common children.
            for attr in ("list", "statements", "ifTrue", "ifFalse", "stmt", "body"):
                v = getattr(stmt, attr, None)
                if v is None:
                    continue
                if hasattr(v, "kind"):
                    _walk_stmts(v, in_alwaysff, in_alwayscomb)
                else:
                    try:
                        for x in v:
                            if hasattr(x, "kind"):
                                _walk_stmts(x, in_alwaysff, in_alwayscomb)
                    except Exception:
                        pass

        for member in body:
            if getattr(member, "kind", None) != _ps.SymbolKind.ProceduralBlock:
                continue
            pkind = str(getattr(member, "procedureKind", ""))
            in_ff = pkind.endswith("AlwaysFF")
            in_comb = pkind.endswith("AlwaysComb") or pkind.endswith("AlwaysLatch") \
                or pkind.endswith("Always")
            stmt = getattr(member, "body", None)
            if stmt is not None:
                _walk_stmts(stmt, in_ff, in_comb)

        # ---- Step 4: emit FSM, FSM_State, has_fsm, has_state edges.
        # Refined criterion: an enum-typed Variable is an FSM only if at
        # least one variable of that enum-type is *also* used as a case
        # selector OR appears in an if/else-if predicate. This filters out
        # configuration registers that happen to be enum-typed (data-only)
        # from real state-holding registers.
        observed_state_use: Set[str] = case_selector_vars | if_condition_vars

        # One FSM per enum-type id. Pick the registered variable as the
        # FSM's representative name.
        fsm_var_per_enum: dict[int, str] = {}
        for eid, vars_ in state_vars.items():
            names = [v.name for v in vars_]
            # Reject enum-types whose variables are never observed in a
            # case selector or if-condition (data-only, not an FSM).
            if not any(n in observed_state_use for n in names):
                continue
            chosen = next((n for n in names if n in nba_lhs_vars), None)
            if chosen is None:
                # Tiebreak: variable that appears as a case selector
                chosen = next((n for n in names if n in case_selector_vars), None)
            if chosen is None:
                chosen = names[0]
            fsm_var_per_enum[eid] = chosen

            # Namespace the FSM entity distinctly from the underlying state
            # variable's Signal entity (``{module}.{varname}``). Without
            # this prefix the NetworkX DiGraph collapses the ``has_fsm``
            # edge into the ``contains`` edge it shares between the same
            # (module, signal) pair.
            fsm_name = f"{def_name}.fsm_{chosen}"
            if fsm_name not in fsm_entities:
                fsm_entities[fsm_name] = Entity(
                    name=fsm_name,
                    type="FSM",
                    extractor_source=["slang"],
                )
            emit(def_name, "has_fsm", fsm_name)

            # Emit one FSM_State entity per enum member.
            for em in enum_members.get(eid, []):
                sname = getattr(em, "name", "") or ""
                if not sname:
                    continue
                state_ent = f"{def_name}.{sname}"
                if state_ent not in fsm_state_entities:
                    fsm_state_entities[state_ent] = Entity(
                        name=state_ent,
                        type="FSM_State",
                        extractor_source=["slang"],
                    )
                emit(fsm_name, "has_state", state_ent)

        # ---- Step 5: emit transitions_to edges.
        # Restrict transition extraction to FSM-qualified enum types only.
        # Variables of rejected (data-only) enum types must not contribute
        # transition edges.
        qualified_state_vars: dict[int, list] = {
            eid: vs for eid, vs in state_vars.items() if eid in fsm_var_per_enum
        }
        # Set of state-typed variable names — used to detect "next-state"
        # assignments (LHS is one of these vars).
        state_var_names: Set[str] = {
            v.name for vs in qualified_state_vars.values() for v in vs
        }
        # Map each state-typed variable name back to its enum id (so we can
        # resolve the FSM for transitions).
        var_to_enum: dict[str, int] = {}
        for eid, vars_ in qualified_state_vars.items():
            for v in vars_:
                var_to_enum[v.name] = eid

        # (src_state, dst_state) -> set(condition_tags). Dedupe across arms.
        transitions: dict[Tuple[str, str], set] = {}

        def _arm_label_names(arm):
            names = []
            for lex in getattr(arm, "expressions", []) or []:
                sym = getattr(lex, "symbol", None)
                if sym is not None and getattr(sym, "kind", None) == _ps.SymbolKind.EnumValue:
                    names.append(getattr(sym, "name", "") or "")
            return [n for n in names if n]

        def _find_state_assignments(stmt, out: list):
            """Collect (lhs_var_name, rhs_enum_name) from state assignments
            inside a case-arm body. Recurses through if/else.
            """
            k = str(getattr(stmt, "kind", ""))
            if k.endswith("ExpressionStatement"):
                e = getattr(stmt, "expr", None)
                if e is None or not str(getattr(e, "kind", "")).endswith("Assignment"):
                    return
                lsym = getattr(getattr(e, "left", None), "symbol", None)
                if lsym is None:
                    return
                lname = getattr(lsym, "name", "") or ""
                if lname not in state_var_names:
                    return
                rsym = getattr(getattr(e, "right", None), "symbol", None)
                if rsym is None or getattr(rsym, "kind", None) != _ps.SymbolKind.EnumValue:
                    return
                rname = getattr(rsym, "name", "") or ""
                if rname:
                    out.append((lname, rname))
                return
            for attr in ("list", "statements", "ifTrue", "ifFalse", "stmt", "body"):
                v = getattr(stmt, attr, None)
                if v is None:
                    continue
                if hasattr(v, "kind"):
                    _find_state_assignments(v, out)
                else:
                    try:
                        for x in v:
                            if hasattr(x, "kind"):
                                _find_state_assignments(x, out)
                    except Exception:
                        pass

        for cs in case_stmts:
            sel_sym = getattr(getattr(cs, "expr", None), "symbol", None)
            if sel_sym is None:
                continue
            sel_name = getattr(sel_sym, "name", "") or ""
            if sel_name not in state_var_names:
                continue
            sel_eid = var_to_enum.get(sel_name)
            if sel_eid is None:
                continue

            for arm in getattr(cs, "items", []) or []:
                labels = _arm_label_names(arm)
                inner = getattr(arm, "stmt", None)
                if inner is None or not labels:
                    continue
                assigns: list = []
                _find_state_assignments(inner, assigns)
                for src_label in labels:
                    src_ent = f"{def_name}.{src_label}"
                    for lhs_var, dst_label in assigns:
                        # Only count assignments whose LHS belongs to the
                        # SAME FSM as the case selector.
                        if var_to_enum.get(lhs_var) != sel_eid:
                            continue
                        dst_ent = f"{def_name}.{dst_label}"
                        cond = f"from={src_label} via={sel_name}"
                        transitions.setdefault((src_ent, dst_ent), set()).add(cond)

        # ---- Step 5b: priority if/else-if ladder transitions.
        # For each ConditionalStatement collected from always_comb/latch
        # blocks, walk the if/else-if chain. For every arm whose THEN body
        # contains an assignment ``state_var = <enum literal>``, emit a
        # transition from the FSM entity (representing "any source state
        # that reaches this assignment") to the destination state.
        #
        # Source-state semantics: when the ladder is NOT enclosed by a
        # ``case (state)`` arm, we cannot statically determine the source
        # state. We choose to emit the edge from the FSM entity itself
        # (``{module}.fsm_{var}``) to the destination state — interpreting
        # this as a "fallthrough" transition that any state reaching the
        # ladder may take. When the predicate references the state
        # variable as ``state == LITERAL``, we additionally emit a more
        # precise edge from that literal state. The rougher fallthrough
        # edge is dropped if a precise one exists for the same dst.
        def _condition_state_literal(pred_expr, sel_name: str) -> str | None:
            """If predicate is ``<sel_name> == ENUM_LIT`` (or symmetric),
            return the enum literal name; otherwise None.
            """
            try:
                k = str(getattr(pred_expr, "kind", ""))
                if not k.endswith("BinaryOp"):
                    return None
                op = str(getattr(pred_expr, "op", ""))
                if "Equality" not in op and op != "BinaryOperator.Equality":
                    return None
                left = getattr(pred_expr, "left", None)
                right = getattr(pred_expr, "right", None)
                lsym = getattr(left, "symbol", None)
                rsym = getattr(right, "symbol", None)
                # state == LIT
                if lsym is not None and getattr(lsym, "name", "") == sel_name \
                        and rsym is not None \
                        and getattr(rsym, "kind", None) == _ps.SymbolKind.EnumValue:
                    return getattr(rsym, "name", "") or None
                # LIT == state
                if rsym is not None and getattr(rsym, "name", "") == sel_name \
                        and lsym is not None \
                        and getattr(lsym, "kind", None) == _ps.SymbolKind.EnumValue:
                    return getattr(lsym, "name", "") or None
            except Exception:
                return None
            return None

        def _walk_ladder(stmt, accumulated_preds: list) -> None:
            """Walk a ConditionalStatement and recurse through ``ifFalse``
            (else-if chains) collecting assignments per arm.

            ``accumulated_preds`` is the list of predicate expressions
            covering the "then" path of this arm. We use the last one as
            the textual evidence; we use the union of NamedValue refs to
            check for a state-equality narrowing.
            """
            k = str(getattr(stmt, "kind", ""))
            if not k.endswith("Conditional"):
                # Terminal "else" branch — treat as an arm with the
                # accumulated negated context. Collect any assignments.
                assigns: list = []
                _find_state_assignments(stmt, assigns)
                _emit_ladder_arm(assigns, accumulated_preds, is_else=True)
                return
            preds = []
            for cond in getattr(stmt, "conditions", []) or []:
                pe = getattr(cond, "expr", None)
                if pe is not None:
                    preds.append(pe)
            then_branch = getattr(stmt, "ifTrue", None)
            else_branch = getattr(stmt, "ifFalse", None)
            if then_branch is not None:
                assigns = []
                _find_state_assignments(then_branch, assigns)
                _emit_ladder_arm(assigns, accumulated_preds + preds, is_else=False)
            if else_branch is not None:
                _walk_ladder(else_branch, accumulated_preds)

        def _emit_ladder_arm(assigns, preds, is_else: bool) -> None:
            for lhs_var, dst_label in assigns:
                eid = var_to_enum.get(lhs_var)
                if eid is None:
                    continue
                fsm_var = fsm_var_per_enum.get(eid)
                if fsm_var is None:
                    continue
                # Try to narrow the source state: if any predicate is
                # ``<state_var_of_this_fsm> == LITERAL``, use that as
                # source. Otherwise emit from the FSM entity itself
                # (fallthrough semantics).
                src_label: str | None = None
                # Iterate all state vars belonging to this FSM's enum.
                fsm_var_names = {
                    v.name for v in qualified_state_vars.get(eid, [])
                }
                for pe in preds:
                    for nm in fsm_var_names:
                        lit = _condition_state_literal(pe, nm)
                        if lit:
                            src_label = lit
                            break
                    if src_label:
                        break
                dst_ent = f"{def_name}.{dst_label}"
                if src_label is not None:
                    src_ent = f"{def_name}.{src_label}"
                    cond = f"from={src_label} via=ladder"
                else:
                    # Fallthrough source: edge from the FSM entity itself.
                    src_ent = f"{def_name}.fsm_{fsm_var_per_enum[eid]}"
                    cond = "from=any via=ladder" + (" else" if is_else else "")
                transitions.setdefault((src_ent, dst_ent), set()).add(cond)

        for cstmt in conditional_stmts:
            _walk_ladder(cstmt, [])

        for (src, dst), conds in transitions.items():
            evidence = "; ".join(sorted(conds))
            emit(src, "transitions_to", dst, evidence_span=evidence)

    def _emit_dataflow_edges(
        self,
        inst: "_ps.InstanceSymbol",
        def_name: str,
        emit,
    ) -> None:
        """Emit ``reads(lhs_signal, rhs_signal)`` for intra-module dataflow.

        Walks the elaborated body for two surfaces:

        * ``SymbolKind.ContinuousAssign`` — has ``.assignment`` (an
          ``AssignmentExpression``) with ``.left`` / ``.right``.
        * ``SymbolKind.ProceduralBlock`` — recursively walks statements,
          looking for ``ExpressionStatement`` whose ``.expr`` is an
          ``Assignment`` (covers blocking ``=``, non-blocking ``<=``,
          and compound assignments). Conditional predicates (``if (en)``)
          are also visited so any signals they reference become reads of
          the LHS within the consequent.

        For each assignment, both LHS base symbols (after descending
        through ``ElementSelect`` / ``RangeSelect`` / ``MemberAccess``)
        and RHS ``NamedValue`` references are filtered to
        **persistent named module-scope signals** — symbols whose
        ``kind`` is one of ``{Port, Variable, Net}`` and whose name
        matches a member declared at module scope. Excludes:

        * Function/task locals and formal arguments
          (``FormalArgument`` / scope is ``Subroutine``).
        * Genvars and generate-block locals.
        * Parameters (constants — captured by ``binds_parameter``).
        * Enum value labels.

        Each assignment produces one ``reads(lhs, rhs)`` triple per
        (LHS, RHS) pair, with the assignment's source text in
        ``evidence_span``. **Bit-slice limitation (Phase 1)**: slices on
        the LHS are NOT modelled as separate nodes — ``data_o[31:24] = a``
        and ``data_o[23:0] = b`` both surface as ``reads(data_o, a)`` and
        ``reads(data_o, b)`` respectively, with the slice text preserved
        in ``evidence_span``. The MultiDiGraph backend keeps each
        observation distinct, so the slice context is recoverable.

        **Distinction from ``drives``**: ``drives`` is for cross-module
        port-to-net connectivity (port connections). ``reads`` is the
        intra-module dataflow inside one module body. The two never
        overlap by construction.
        """
        try:
            body = inst.body
        except Exception:
            return

        # ------------------------------------------------------------------
        # Build module-scope name -> kind map. Only Port/Variable/Net are
        # considered persistent named signals. Note: pyslang surfaces ports
        # as both Port AND Variable (the backing storage); we collapse on
        # name. Parameters and Genvars are intentionally excluded.
        # ------------------------------------------------------------------
        module_scope_signals: Set[str] = set()
        for member in body:
            try:
                kind = getattr(member, "kind", None)
                name = getattr(member, "name", "") or ""
            except UnicodeDecodeError:
                continue
            if not name:
                continue
            if kind in (
                _ps.SymbolKind.Port,
                _ps.SymbolKind.Net,
                _ps.SymbolKind.Variable,
            ):
                module_scope_signals.add(name)

        if not module_scope_signals:
            return

        def _slice_text_from_select(node) -> Optional[str]:
            """Return the bracketed slice text for an ``ElementSelect`` /
            ``RangeSelect`` expression node — e.g. ``"[31:24]"``,
            ``"[ADDR_W-1:0]"``, ``"[5]"`` — preserved symbolically.

            Implementation: stringify the full select syntax, drop the
            inner base value's text, and trim whitespace. ``None`` is
            returned when the slice cannot be reconstructed.
            """
            try:
                full = str(getattr(node, "syntax", node)).strip()
            except Exception:
                return None
            inner = getattr(node, "value", None)
            try:
                inner_txt = str(getattr(inner, "syntax", inner)).strip() \
                    if inner is not None else ""
            except Exception:
                inner_txt = ""
            if inner_txt and full.startswith(inner_txt):
                bracketed = full[len(inner_txt):].strip()
                if bracketed.startswith("[") and bracketed.endswith("]"):
                    return bracketed
            # Fallback: extract the trailing bracketed run.
            if full.endswith("]"):
                depth = 0
                for i in range(len(full) - 1, -1, -1):
                    ch = full[i]
                    if ch == "]":
                        depth += 1
                    elif ch == "[":
                        depth -= 1
                        if depth == 0:
                            return full[i:].strip()
            return None

        def _is_select_kind(node) -> bool:
            ks = str(getattr(node, "kind", "") or "")
            return ks.endswith("ElementSelect") or ks.endswith("RangeSelect")

        def _is_persistent_named_value(node) -> Optional[str]:
            """Return the module-scope signal name if ``node`` is a
            ``NamedValue`` referencing one, else ``None``."""
            ks = str(getattr(node, "kind", "") or "")
            if not ks.endswith("NamedValue"):
                return None
            sym = getattr(node, "symbol", None)
            if sym is None:
                return None
            try:
                sym_kind = getattr(sym, "kind", None)
                sym_name = getattr(sym, "name", "") or ""
            except UnicodeDecodeError:
                return None
            if not sym_name:
                return None
            if sym_kind not in (
                _ps.SymbolKind.Port,
                _ps.SymbolKind.Net,
                _ps.SymbolKind.Variable,
            ):
                return None
            if sym_name not in module_scope_signals:
                return None
            return sym_name

        def _collect_base_symbols(expr) -> List[str]:
            """Return persistent module-scope signal names referenced.

            Walks an expression visiting ``NamedValue`` leaves; descends
            through ``ElementSelect`` / ``RangeSelect`` / ``MemberAccess``
            implicitly because pyslang's ``visit`` recurses into ``.value``
            children automatically.
            """
            names: list = []

            def _vis(node) -> None:
                n = _is_persistent_named_value(node)
                if n is not None:
                    names.append(n)

            try:
                expr.visit(_vis)
            except Exception:
                return names
            return names

        def _collect_base_symbols_with_slice(
            expr,
        ) -> List[Tuple[str, Optional[str]]]:
            """Like ``_collect_base_symbols`` but each result is paired
            with the symbolic slice text (or ``None``) of the immediately
            wrapping ``ElementSelect`` / ``RangeSelect``, if any.

            Implementation: single pyslang ``visit`` pass. pyslang's
            depth-first preorder visits a Select expression immediately
            before its inner ``.value`` child, so we use a ``pending``
            slot: a Select stashes its slice text there; the *next*
            NamedValue consumes it. Object-identity matching is
            unreliable here because pyslang re-issues fresh Python
            wrappers around the same C++ node — so we don't try.

            For nested selects (``a[7:0][3]``) the outer slice wins:
            an already-set ``pending`` is not overwritten by an inner
            Select.
            """
            results: List[Tuple[str, Optional[str]]] = []
            pending: List[Optional[str]] = [None]

            def _vis(node) -> None:
                if _is_select_kind(node):
                    if pending[0] is None:
                        pending[0] = _slice_text_from_select(node)
                    return
                n = _is_persistent_named_value(node)
                if n is None:
                    return
                sl = pending[0]
                pending[0] = None
                results.append((n, sl))

            try:
                expr.visit(_vis)
            except Exception:
                pass

            seen: Set[Tuple[str, Optional[str]]] = set()
            uniq: List[Tuple[str, Optional[str]]] = []
            for pair in results:
                if pair in seen:
                    continue
                seen.add(pair)
                uniq.append(pair)
            return uniq

        def _expr_text(expr) -> str:
            try:
                syn = getattr(expr, "syntax", None)
                if syn is not None:
                    return str(syn).strip()
            except Exception:
                pass
            try:
                return str(expr).strip()
            except Exception:
                return ""

        def _emit_for_assignment(assign_expr) -> None:
            try:
                lhs = getattr(assign_expr, "left", None)
                rhs = getattr(assign_expr, "right", None)
            except Exception:
                return
            if lhs is None or rhs is None:
                return
            lhs_pairs = _collect_base_symbols_with_slice(lhs)
            if not lhs_pairs:
                return
            rhs_pairs = _collect_base_symbols_with_slice(rhs)
            if not rhs_pairs:
                return
            evidence = _expr_text(assign_expr)
            # Dedupe (lhs, rhs, lhs_slice, rhs_slice) pairs *within* this
            # single assignment so ``a + a`` doesn't emit two identical
            # triples for the same statement (the MultiDiGraph would still
            # store both, but the second one carries no extra information).
            seen_pair: Set[Tuple[str, str, Optional[str], Optional[str]]] = \
                set()
            for lname, l_slice in lhs_pairs:
                for rname, r_slice in rhs_pairs:
                    if lname == rname:
                        continue
                    key = (lname, rname, l_slice, r_slice)
                    if key in seen_pair:
                        continue
                    seen_pair.add(key)
                    emit(
                        f"{def_name}.{lname}",
                        "reads",
                        f"{def_name}.{rname}",
                        evidence_span=evidence,
                        lhs_slice=l_slice,
                        rhs_slice=r_slice,
                    )

        def _walk_stmts(stmt) -> None:
            kind_str = str(getattr(stmt, "kind", ""))
            if kind_str.endswith("ExpressionStatement"):
                e = getattr(stmt, "expr", None)
                if e is not None:
                    ek = str(getattr(e, "kind", ""))
                    if ek.endswith("Assignment"):
                        _emit_for_assignment(e)
                return
            if kind_str.endswith("Conditional"):
                # Predicate signals are reads of every assignment LHS in
                # the consequent. Easiest model: walk the predicate as
                # part of the synthesized RHS by treating each branch's
                # assignments as if their RHS were augmented. We emit
                # (lhs <- predicate_signal) edges for every assignment
                # found inside the THEN/ELSE branches.
                preds: list = []
                for cond in getattr(stmt, "conditions", []) or []:
                    pe = getattr(cond, "expr", None)
                    if pe is not None:
                        preds.append(pe)
                pred_names: list = []
                pred_text_parts: list = []
                for pe in preds:
                    pred_names.extend(_collect_base_symbols(pe))
                    t = _expr_text(pe)
                    if t:
                        pred_text_parts.append(t)
                pred_names_unique = list(dict.fromkeys(pred_names))

                def _branch(branch_stmt) -> None:
                    if branch_stmt is None:
                        return
                    # Recurse normally for assignments within the branch.
                    _walk_stmts(branch_stmt)
                    # Additionally: for every direct/indirect assignment
                    # inside this branch, emit reads(lhs, pred) edges.
                    if not pred_names_unique:
                        return
                    lhs_collector: list = []
                    _collect_lhs_in_branch(branch_stmt, lhs_collector)
                    pred_text = " && ".join(pred_text_parts)
                    for lname in lhs_collector:
                        for pname in pred_names_unique:
                            if lname == pname:
                                continue
                            emit(
                                f"{def_name}.{lname}",
                                "reads",
                                f"{def_name}.{pname}",
                                evidence_span=f"if ({pred_text})",
                            )

                _branch(getattr(stmt, "ifTrue", None))
                _branch(getattr(stmt, "ifFalse", None))
                return
            # Generic recursion across common children.
            for attr in ("list", "statements", "ifTrue", "ifFalse",
                         "stmt", "body"):
                v = getattr(stmt, attr, None)
                if v is None:
                    continue
                if hasattr(v, "kind"):
                    _walk_stmts(v)
                else:
                    try:
                        for x in v:
                            if hasattr(x, "kind"):
                                _walk_stmts(x)
                    except Exception:
                        pass

        def _collect_lhs_in_branch(stmt, out: list) -> None:
            """Collect LHS persistent signal names of any assignment
            reachable from ``stmt`` (used to emit predicate-conditioned
            reads edges)."""
            kind_str = str(getattr(stmt, "kind", ""))
            if kind_str.endswith("ExpressionStatement"):
                e = getattr(stmt, "expr", None)
                if e is not None and str(getattr(e, "kind", "")).endswith("Assignment"):
                    lhs = getattr(e, "left", None)
                    if lhs is not None:
                        out.extend(_collect_base_symbols(lhs))
                return
            for attr in ("list", "statements", "ifTrue", "ifFalse",
                         "stmt", "body"):
                v = getattr(stmt, attr, None)
                if v is None:
                    continue
                if hasattr(v, "kind"):
                    _collect_lhs_in_branch(v, out)
                else:
                    try:
                        for x in v:
                            if hasattr(x, "kind"):
                                _collect_lhs_in_branch(x, out)
                    except Exception:
                        pass

        # ------------------------------------------------------------------
        # Walk ContinuousAssign + ProceduralBlock members.
        # ------------------------------------------------------------------
        for member in body:
            mkind = getattr(member, "kind", None)
            if mkind == _ps.SymbolKind.ContinuousAssign:
                a = getattr(member, "assignment", None)
                if a is not None:
                    _emit_for_assignment(a)
            elif mkind == _ps.SymbolKind.ProceduralBlock:
                stmt = getattr(member, "body", None)
                if stmt is not None:
                    _walk_stmts(stmt)

    def _emit_bind_directive_edges(
        self,
        compilation: "_ps.Compilation",
        emit,
    ) -> None:
        """Emit ``bound_into`` edges for every SystemVerilog ``bind`` directive.

        We walk the syntax-tree level (``BindDirectiveSyntax``) rather than the
        elaborated symbol tree because:

        * Pyslang does not expose a dedicated ``BindDirective`` symbol kind —
          it splices the bound instance silently into the target's body, and
          the resulting ``InstanceSymbol`` is indistinguishable from a normal
          child instance.
        * When the bind source module is missing from the parsed file set
          (e.g. ``bind aes aes_csr_assert_fpv u_inst(...)`` when
          ``aes_csr_assert_fpv`` is not provided), elaboration silently drops
          the directive — we still want the edge as an audit signal that the
          bind references a missing module.

        For each directive ``bind <target> <bound_def> <inst>(...);`` we emit
        one triple per declared instance:
            subject=<bound_def>, predicate=bound_into, object=<target>
        with ``evidence_span`` carrying the instance name.
        """
        try:
            trees = compilation.getSyntaxTrees()
        except Exception as exc:
            logger.debug("getSyntaxTrees unavailable: %s", exc)
            return

        seen: Set[Tuple[str, str, str]] = set()
        for tree in trees:
            try:
                root_node = tree.root
            except Exception:
                continue
            self._walk_syntax_for_binds(root_node, emit, seen)

    def _walk_syntax_for_binds(self, node, emit, seen: Set[Tuple[str, str, str]]) -> None:
        """Recursively scan a syntax node for ``BindDirectiveSyntax`` children."""
        try:
            kind = node.kind
        except Exception:
            return
        if kind == _ps.SyntaxKind.BindDirective:
            self._emit_one_bind_directive(node, emit, seen)
            # No need to recurse into the directive itself.
            return
        # Generic descent: BindDirectives appear at compilation-unit /
        # module-body scope, so we walk children of any container node.
        try:
            for child in node:
                if child is None:
                    continue
                self._walk_syntax_for_binds(child, emit, seen)
        except TypeError:
            # Non-iterable syntax nodes — nothing to descend.
            return
        except Exception:
            return

    def _emit_one_bind_directive(
        self, directive, emit, seen: Set[Tuple[str, str, str]],
    ) -> None:
        """Emit ``bound_into`` edges for a single ``BindDirectiveSyntax`` node."""
        try:
            target = directive.target
            inst_syntax = directive.instantiation
        except Exception:
            return
        if target is None or inst_syntax is None:
            return

        # Target identifier — module being bound INTO.
        target_name = ""
        try:
            target_name = (target.identifier.value or "").strip()
        except Exception:
            try:
                target_name = str(target).strip()
            except Exception:
                target_name = ""
        if not target_name:
            return

        # Bound module/interface definition name.
        bound_def = ""
        try:
            type_tok = inst_syntax.type
            bound_def = (type_tok.value or type_tok.valueText or "").strip()
        except Exception:
            bound_def = ""
        if not bound_def:
            return

        # Iterate each declared instance — one bind directive may declare
        # multiple instances (`bind a b u1(), u2();`).
        try:
            instances = list(inst_syntax.instances)
        except Exception:
            instances = []
        if not instances:
            # Fall back to a single edge with no instance name.
            key = (bound_def, "bound_into", target_name)
            if key not in seen:
                seen.add(key)
                emit(bound_def, "bound_into", target_name)
            return

        for hi in instances:
            inst_name = ""
            try:
                inst_name = (hi.decl.name.value or "").strip()
            except Exception:
                try:
                    inst_name = str(hi.decl).strip()
                except Exception:
                    inst_name = ""
            key = (bound_def, "bound_into", target_name)
            if key in seen:
                continue
            seen.add(key)
            emit(
                bound_def,
                "bound_into",
                target_name,
                evidence_span=inst_name,
            )

    def _emit_covergroup_edges(
        self,
        inst: "_ps.InstanceSymbol",
        def_name: str,
        emit,
        cov_entities: dict,
    ) -> None:
        """Emit Covergroup_SV / Coverpoint / CoverBin / CoverCross entities.

        Pyslang surfaces SystemVerilog covergroups as
        ``SymbolKind.CovergroupType`` symbols at module-body scope. Each one
        contains a ``SymbolKind.CovergroupBody`` whose direct children are the
        ``SymbolKind.Coverpoint``, ``SymbolKind.CoverCross``, and a few
        synthesised helper subroutines / class properties (``option``,
        ``sample``, ``start``...). We extract:

        * One ``Covergroup_SV`` entity per ``CovergroupType``, named
          ``{module}.{cg_name}``.
        * One ``defined_in`` edge from the covergroup to its enclosing module.
        * One ``Coverpoint`` entity per ``Coverpoint`` child, named
          ``{module}.{cg_name}.{cp_name}`` (anonymous coverpoints get a
          synthetic ``cp_<idx>`` index).
        * One ``has_coverpoint`` edge per coverpoint.
        * For each coverpoint whose ``coverageExpr`` is a single ``NamedValue``
          (or ``Conversion`` wrapping a ``NamedValue``) resolving to a
          module-scope ``Port``/``Net``/``Variable``, emit an ``observes`` edge
          to the canonical ``{module}.{signal}`` node.
        * For each coverpoint whose ``coverageExpr`` resolves to a
          ``FormalArgument`` of the covergroup's ``with function sample(...)``
          subroutine, emit a ``Covergroup_SampleArg`` entity named
          ``{module}.{cg_name}.arg.{arg_name}``, a ``has_sample_arg``
          composition edge from the covergroup, and an ``observes`` edge from
          the coverpoint to the SampleArg node.  Only one SampleArg entity
          is emitted per unique arg name (multiple coverpoints may share an
          arg).
        * Complex expressions (slices, concatenations, function calls) are
          intentionally skipped in Phase 1 — they produce no ``observes`` edge.
        * One ``CoverBin`` entity per ``CoverageBin`` grandchild, named
          ``{module}.{cg_name}.{cp_name}.{bin_name}``, plus a ``has_bin`` edge.
        * One ``CoverCross`` entity per ``CoverCross`` child (anonymous
          crosses get a synthetic ``cross_<idx>`` index), one ``has_cross``
          edge, and one ``crosses`` edge per target coverpoint.
        """
        try:
            body = inst.body
        except Exception:
            return

        module_signals: Set[str] = set()
        for member in body:
            try:
                kind = getattr(member, "kind", None)
                name = getattr(member, "name", "") or ""
            except UnicodeDecodeError:
                continue
            if not name:
                continue
            if kind in (
                _ps.SymbolKind.Port,
                _ps.SymbolKind.Net,
                _ps.SymbolKind.Variable,
            ):
                module_signals.add(name)

        anon_cg_idx = 0
        for member in body:
            if getattr(member, "kind", None) != _ps.SymbolKind.CovergroupType:
                continue

            try:
                cg_name = member.name or ""
            except UnicodeDecodeError:
                continue
            if not cg_name:
                cg_name = f"covergroup_{anon_cg_idx}"
                anon_cg_idx += 1
            cg_ent_name = f"{def_name}.{cg_name}"

            # Locate the CovergroupBody scope (skip the synthetic helpers).
            cg_body = None
            for child in member:
                if getattr(child, "kind", None) == _ps.SymbolKind.CovergroupBody:
                    cg_body = child
                    break
            if cg_body is None:
                continue

            if cg_ent_name not in cov_entities:
                cov_entities[cg_ent_name] = Entity(
                    name=cg_ent_name,
                    type="Covergroup_SV",
                    extractor_source=["slang"],
                    raw_mentions=[],
                )
            emit(cg_ent_name, "defined_in", def_name)

            anon_cp_idx = 0
            anon_cross_idx = 0
            for cb_child in cg_body:
                cb_kind = getattr(cb_child, "kind", None)
                if cb_kind == _ps.SymbolKind.Coverpoint:
                    try:
                        cp_name = cb_child.name or ""
                    except UnicodeDecodeError:
                        cp_name = ""
                    if not cp_name:
                        cp_name = f"cp_{anon_cp_idx}"
                        anon_cp_idx += 1
                    cp_ent_name = f"{cg_ent_name}.{cp_name}"

                    if cp_ent_name not in cov_entities:
                        cov_entities[cp_ent_name] = Entity(
                            name=cp_ent_name,
                            type="Coverpoint",
                            extractor_source=["slang"],
                            raw_mentions=[],
                        )
                    emit(cg_ent_name, "has_coverpoint", cp_ent_name)

                    # ``observes``: emit when coverageExpr is a single
                    # NamedValue resolving to a module-scope Port/Net/Variable
                    # (original path) or to a FormalArgument of the
                    # covergroup's synthesised sample() subroutine (new path).
                    # Slang wraps FormalArgument refs in a Conversion node
                    # when the arg type needs widening; we unwrap one level.
                    # Complex expressions (slices, casts, function calls) are
                    # intentionally skipped in Phase 1 — they produce no edge.
                    try:
                        cov_expr = getattr(cb_child, "coverageExpr", None)
                    except Exception:
                        cov_expr = None
                    if cov_expr is not None:
                        ek = str(getattr(cov_expr, "kind", "") or "")
                        # Unwrap one level of implicit Conversion so that
                        # ``coverpoint x`` (where x is a FormalArgument)
                        # resolves to its underlying NamedValue.
                        named_expr = cov_expr
                        if ek.endswith("Conversion"):
                            try:
                                operand = getattr(cov_expr, "operand", None)
                                if operand is not None:
                                    ok = str(
                                        getattr(operand, "kind", "") or ""
                                    )
                                    if ok.endswith("NamedValue"):
                                        named_expr = operand
                                        ek = ok
                            except Exception:
                                pass
                        if ek.endswith("NamedValue"):
                            sym = getattr(named_expr, "symbol", None)
                            if sym is not None:
                                try:
                                    sym_kind = getattr(sym, "kind", None)
                                    sym_name = getattr(sym, "name", "") or ""
                                except UnicodeDecodeError:
                                    sym_kind = None
                                    sym_name = ""
                                if sym_name and sym_kind in (
                                    _ps.SymbolKind.Port,
                                    _ps.SymbolKind.Net,
                                    _ps.SymbolKind.Variable,
                                ) and sym_name in module_signals:
                                    # Existing path: module-scope signal.
                                    emit(cp_ent_name, "observes",
                                         f"{def_name}.{sym_name}")
                                elif sym_name and sym_kind == (
                                    _ps.SymbolKind.FormalArgument
                                ):
                                    # New path: sample-function argument.
                                    # Emit a Covergroup_SampleArg node
                                    # (composition under the covergroup) and
                                    # wire the coverpoint to it.
                                    arg_ent_name = (
                                        f"{cg_ent_name}.arg.{sym_name}"
                                    )
                                    if arg_ent_name not in cov_entities:
                                        cov_entities[arg_ent_name] = Entity(
                                            name=arg_ent_name,
                                            type="Covergroup_SampleArg",
                                            extractor_source=["slang"],
                                            raw_mentions=[],
                                        )
                                        emit(cg_ent_name, "has_sample_arg",
                                             arg_ent_name)
                                    emit(cp_ent_name, "observes",
                                         arg_ent_name)

                    # Bins.
                    for bin_child in cb_child:
                        if getattr(bin_child, "kind", None) != \
                                _ps.SymbolKind.CoverageBin:
                            continue
                        try:
                            bin_name = bin_child.name or ""
                        except UnicodeDecodeError:
                            continue
                        if not bin_name:
                            continue
                        bin_ent_name = f"{cp_ent_name}.{bin_name}"
                        if bin_ent_name not in cov_entities:
                            cov_entities[bin_ent_name] = Entity(
                                name=bin_ent_name,
                                type="CoverBin",
                                extractor_source=["slang"],
                                raw_mentions=[],
                            )
                        emit(cp_ent_name, "has_bin", bin_ent_name)

                elif cb_kind == _ps.SymbolKind.CoverCross:
                    try:
                        cx_name = cb_child.name or ""
                    except UnicodeDecodeError:
                        cx_name = ""
                    if not cx_name:
                        cx_name = f"cross_{anon_cross_idx}"
                        anon_cross_idx += 1
                    cx_ent_name = f"{cg_ent_name}.{cx_name}"
                    if cx_ent_name not in cov_entities:
                        cov_entities[cx_ent_name] = Entity(
                            name=cx_ent_name,
                            type="CoverCross",
                            extractor_source=["slang"],
                            raw_mentions=[],
                        )
                    emit(cg_ent_name, "has_cross", cx_ent_name)

                    targets = getattr(cb_child, "targets", None) or []
                    seen_targets: Set[str] = set()
                    for tgt in targets:
                        try:
                            tname = getattr(tgt, "name", "") or ""
                        except UnicodeDecodeError:
                            continue
                        if not tname:
                            continue
                        target_ent = f"{cg_ent_name}.{tname}"
                        if target_ent in seen_targets:
                            continue
                        seen_targets.add(target_ent)
                        emit(cx_ent_name, "crosses", target_ent)

    @staticmethod
    def _iter_signal_events(timing):
        """Yield SignalEvent timing-control nodes from a TimingControl.

        Handles three shapes:
          * ``SignalEvent``  — single-edge always_ff
          * ``EventList``    — multiple edges joined by ``or``
          * any other kind   — yield nothing (e.g. delay controls).
        """
        kind_str = str(getattr(timing, "kind", ""))
        if kind_str.endswith("SignalEvent"):
            yield timing
            return
        if kind_str.endswith("EventList"):
            for ev in getattr(timing, "events", []) or []:
                inner_kind = str(getattr(ev, "kind", ""))
                if inner_kind.endswith("SignalEvent"):
                    yield ev

    @staticmethod
    def _collect_named_value_paths(expr) -> List[str]:
        """Return the hierarchical paths of all NamedValue leaves in ``expr``."""
        leaves: List[str] = []

        def visitor(node) -> None:
            kind = getattr(node, "kind", None)
            if kind is None:
                return
            if str(kind).endswith("NamedValue"):
                sym = getattr(node, "symbol", None)
                if sym is None:
                    return
                path = getattr(sym, "hierarchicalPath", "") or ""
                path = path.strip()
                if path:
                    leaves.append(path)

        try:
            expr.visit(visitor)
        except Exception:
            pass
        return leaves


# Back-compat alias: existing call sites import SVConnectivityAnalyzer.
SVConnectivityAnalyzer = SlangHierarchyAnalyzer
