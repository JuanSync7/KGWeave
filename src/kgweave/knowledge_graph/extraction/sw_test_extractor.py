# @summary
# Bare-metal SW regression test extractor (Tier 1 + Tier 2).
# Walks a directory for *.c files, emits SW_Test entities, and links each
# test to known RTL_Module / CSR_Register entities via a config-driven
# pattern engine (V3 Tier A). Default config replicates OpenTitan's three
# original signals: DIF header #include basenames, dif_<mod>_*( calls, and
# *_<MODNAME>_BASE_ADDR address constants. Falls back to a low-tier
# unresolved sentinel when no pattern matches on a real test file.
# Exports: SWTestExtractor, SW_TEST_SOURCE
# Deps: pathlib, re, typing, kgweave.knowledge_graph.common
# @end-summary
"""Bare-metal SW regression test extractor (config-driven).

Walks a directory for C source files (``*.c``) and emits:
  - ``SW_Test`` entity per file (canonical: basename without ``.c``).
  - ``tests_module`` edge: SW_Test → RTL_Module via config-driven regex
    patterns. The default config contains three OpenTitan-flavored patterns:
    DIF header ``#include`` basenames, ``dif_<mod>_*(`` calls, and
    ``*_<MODNAME>_BASE_ADDR`` constants.
  - ``accesses_csr`` edge: SW_Test → CSR_Register for each
    ``<MODULE>_<REG>_REG_OFFSET`` / ``<MODULE>_<REG>_OFFSET`` constant
    referenced via ``mmio_*`` calls or bare offset references. Synthetic
    CSR access edges are also emitted for modules resolved through the
    ``dif_api_call`` pattern (Tier-2 heuristic).
  - Low-tier unresolved ``tests_module`` sentinel edge to ``<unknown>``
    when ``is_test=True`` AND no pattern resolved.

V3 Tier A: the resolver is now a generic pattern engine driven by
``SwTestResolutionConfig``. Project teams can supply YAML describing
their conventions (camelCase modules, vendor macros, no DIF prefix)
without touching this file. With no config supplied, behavior is
byte-identical to the prior OpenTitan-hardcoded resolver.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)
from kgweave.knowledge_graph.common.sw_test_buildsys import (
    BuildSystemLink,
    BuildSystemReader,
    discover_links,
)
from kgweave.knowledge_graph.common.sw_test_config import (
    SwTestResolutionConfig,
    load_sw_test_config,
)

__all__ = ["SWTestExtractor", "SW_TEST_SOURCE"]

SW_TEST_SOURCE = "sw_test"

_logger = logging.getLogger("rag.knowledge_graph.sw_test_extractor")

# CSR-access scans (orthogonal to the configurable tests_module patterns).
# These OT-flavored defaults are kept for legacy bare-construction back-compat
# (SWTestExtractor() with no project_conventions). New code should pass
# ProjectConventions or explicit constructor args.
_DEFAULT_CSR_ACCESS_API_PATTERNS = (
    "mmio_region_write32",
    "mmio_region_read32",
    "abs_mmio_write32",
    "abs_mmio_read32",
)
_DEFAULT_CSR_OFFSET_SUFFIXES = ("_REG_OFFSET", "_OFFSET")

_MMIO_OFFSET_RE = re.compile(
    r"\b(?:mmio_region_write32|mmio_region_read32|abs_mmio_write32|abs_mmio_read32)"
    r"\s*\([^;)]*\b(\w+_REG_OFFSET|\w+_OFFSET)\b"
)
_BARE_OFFSET_RE = re.compile(r"\b([A-Z][A-Z0-9_]+_REG_OFFSET)\b")


def _build_mmio_regex(api_patterns: List[str], suffixes: List[str]) -> Optional[re.Pattern]:
    """Compile the MMIO-API-with-offset regex from an api list and suffix list."""
    if not api_patterns or not suffixes:
        return None
    api_alt = "|".join(re.escape(a) for a in api_patterns)
    suf_alt = "|".join(rf"\w+{re.escape(s)}" for s in suffixes)
    return re.compile(
        rf"\b(?:{api_alt})\s*\([^;)]*\b({suf_alt})\b"
    )


def _build_bare_offset_regex(suffixes: List[str]) -> Optional[re.Pattern]:
    """Compile a bare-offset regex matching ``[A-Z_]+<suffix>``.

    Only the most identifying suffix (``_REG_OFFSET`` if present) is used —
    the bare-offset scan is intentionally conservative. Bare uppercase
    identifiers ending in plain ``_OFFSET`` would over-match (e.g. struct
    field offset macros), so we restrict to the long-form suffix when
    available; otherwise fall through to the full suffix list.
    """
    if not suffixes:
        return None
    if "_REG_OFFSET" in suffixes:
        suf_alt = re.escape("_REG_OFFSET")
    else:
        suf_alt = "|".join(re.escape(s) for s in suffixes)
    return re.compile(rf"\b([A-Z][A-Z0-9_]+(?:{suf_alt}))\b")

_MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Pattern name that triggers synthetic CSR access edges (preserves the
# legacy "DIF call seen → module's CSRs are accessed" Tier-2 heuristic).
OPENTITAN_DIF_PATTERN_NAME = "dif_api_call"


@dataclass
class _ModuleClaimIndex:
    """Set of canonical module names usable as resolution targets.

    Built once at extractor init from ``known_entity_names``, filtered to
    identifier-like names that look like RTL modules (``^[a-z][a-z0-9_]*$``).
    The pattern engine resolves a captured module name against this set
    (case-insensitive after the pattern's transform has been applied).
    """

    _modules: Set[str] = field(default_factory=set)
    _by_lower: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, names: Iterable[str]) -> "_ModuleClaimIndex":
        idx = cls()
        for n in names or ():
            if not n or not _MODULE_NAME_RE.match(n):
                continue
            idx._modules.add(n)
            idx._by_lower[n.lower()] = n
        return idx

    def modules(self) -> Set[str]:
        return set(self._modules)

    def resolve(self, captured: str) -> Optional[str]:
        """Resolve a captured (post-transform) module name to canonical form.

        Falls back to a case-insensitive lookup so configs that emit
        uppercase identifiers (without an explicit lowercase transform)
        still hit the index.
        """
        if not captured:
            return None
        if captured in self._modules:
            return captured
        return self._by_lower.get(captured.lower())


class SWTestExtractor:
    """Bare-metal SW test extractor: config-driven module resolver.

    Parameters
    ----------
    known_entity_names:
        Iterable of canonical entity names from the KG. Used for two
        fusion operations:
          1. Module resolution: identifier-like names (``^[a-z][a-z0-9_]*$``)
             are indexed and matched against module names captured by each
             configured pattern (after applying the pattern's transform).
          2. CSR-register matching: ``<module>.<reg>`` names found in the
             KG are matched against offset constants.
    schema, config:
        Accepted for symmetry with other extractors; not used.
    sw_test_config:
        Optional ``SwTestResolutionConfig`` overriding the OpenTitan
        defaults. When ``None``, the default config is loaded via
        ``load_sw_test_config(None)``.
    """

    __test__ = False

    @property
    def name(self) -> str:
        return SW_TEST_SOURCE

    def __init__(
        self,
        known_entity_names: Optional[Iterable[str]] = None,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
        sw_test_config: Optional[SwTestResolutionConfig] = None,
        project_conventions: Optional[Any] = None,
        csr_access_api_patterns: Optional[List[str]] = None,
        csr_offset_suffixes: Optional[List[str]] = None,
        sw_test_extensions: Optional[List[str]] = None,
        recursive: bool = False,
    ) -> None:
        self._schema = schema
        self._config = config
        self._project_conventions = project_conventions
        if sw_test_config is None:
            self._sw_test_config = load_sw_test_config(
                None, project_conventions=project_conventions
            )
        else:
            self._sw_test_config = sw_test_config
        names = list(known_entity_names) if known_entity_names else []
        self._known_lower: dict[str, str] = {}
        for n in names:
            if n:
                self._known_lower[n.lower()] = n
        self._claim_index = _ModuleClaimIndex.build(names)

        # --- CSR access API patterns + offset suffixes ---
        # Resolution order: explicit constructor arg > project_conventions
        # field > legacy OT default (only when no project_conventions
        # supplied — strict-generic mode emits zero accesses_csr edges
        # rather than guessing).
        explicit_pc = project_conventions is not None
        if csr_access_api_patterns is None:
            if explicit_pc:
                pc_apis = getattr(
                    project_conventions, "csr_access_api_patterns", None
                )
                if pc_apis:
                    csr_access_api_patterns = list(pc_apis)
                elif getattr(project_conventions, "profile", None) == "opentitan":
                    csr_access_api_patterns = list(_DEFAULT_CSR_ACCESS_API_PATTERNS)
                else:
                    csr_access_api_patterns = []
            else:
                csr_access_api_patterns = list(_DEFAULT_CSR_ACCESS_API_PATTERNS)

        if csr_offset_suffixes is None:
            if explicit_pc:
                pc_suf = getattr(project_conventions, "csr_offset_suffixes", None)
                csr_offset_suffixes = (
                    list(pc_suf) if pc_suf else list(_DEFAULT_CSR_OFFSET_SUFFIXES)
                )
            else:
                csr_offset_suffixes = list(_DEFAULT_CSR_OFFSET_SUFFIXES)

        self._csr_offset_suffixes: List[str] = list(csr_offset_suffixes)
        self._mmio_re = _build_mmio_regex(
            list(csr_access_api_patterns), self._csr_offset_suffixes
        )
        self._bare_offset_re = _build_bare_offset_regex(self._csr_offset_suffixes)
        if not csr_access_api_patterns:
            _logger.debug(
                "SWTestExtractor: csr_access_api_patterns is empty; "
                "no MMIO accesses_csr edges will be emitted."
            )

        # --- File walk: extensions + recursion ---
        if sw_test_extensions is None:
            if explicit_pc:
                pc_exts = getattr(project_conventions, "sw_test_extensions", None)
                sw_test_extensions = list(pc_exts) if pc_exts else [".c"]
            else:
                sw_test_extensions = [".c"]
        self._sw_test_extensions: List[str] = list(sw_test_extensions)
        self._recursive: bool = bool(recursive)

        # Synthetic CSR pattern name. Resolution: explicit project_conventions
        # field > legacy default ("dif_api_call") for naked construction (back-compat).
        if explicit_pc:
            self._synthetic_csr_pattern: Optional[str] = getattr(
                project_conventions, "synthetic_csr_from_pattern", None
            )
            self._evidence_include_tpl: Optional[str] = getattr(
                project_conventions, "evidence_format_include_template", None
            )
            self._evidence_call_tpl: Optional[str] = getattr(
                project_conventions, "evidence_format_call_template", None
            )
        else:
            self._synthetic_csr_pattern = OPENTITAN_DIF_PATTERN_NAME
            self._evidence_include_tpl = '#include "dif_{module}.h"'
            self._evidence_call_tpl = "dif_{module}_* call"

    def extract(
        self,
        text: str = "",
        source: str = "",
        project_root: Optional[Path] = None,
        build_system_readers: Optional[List[BuildSystemReader]] = None,
    ) -> ExtractionResult:
        """Walk a directory and extract SW_Test entities and edges.

        Parameters
        ----------
        text:
            Ignored; SW extraction is directory-driven.
        source:
            Directory containing C test files.
        project_root:
            Optional Tier-B project root. When provided, the configured
            build-system readers run first and any discovered
            ``(test_path, module)`` link is treated as authoritative —
            it overrides regex pattern matches for the same pair.
            When ``None`` (the default), behavior is byte-identical to
            Tier-A: regex patterns only.
        build_system_readers:
            Override the reader registry (primarily for tests). When
            ``None`` and ``project_root`` is given, the default
            registry is used (all readers disabled by default; opt in
            via ``SwTestBuildSystemConfig``).
        """
        if not source:
            return ExtractionResult()

        sw_dir = Path(source)
        if not sw_dir.is_dir():
            _logger.warning(
                "SW test directory does not exist or is not a directory: %s",
                source,
            )
            return ExtractionResult()

        ext_set = {e.lower() for e in self._sw_test_extensions}
        if self._recursive:
            iterator = sw_dir.rglob("*")
        else:
            iterator = sw_dir.iterdir()
        c_files = sorted(
            p for p in iterator
            if p.is_file() and p.suffix.lower() in ext_set
        )
        if not c_files:
            _logger.debug("No *.c files found in %s", sw_dir)
            return ExtractionResult()

        if not self._known_lower:
            raise ValueError(
                "SWTestExtractor requires non-empty known_entity_names — "
                "run RTL extraction first or pass the entity list explicitly."
            )

        # Tier B: discover authoritative build-system links first. The
        # bs_index maps test_path basename → list[BuildSystemLink] so the
        # per-file resolver can both (a) emit those edges and (b) suppress
        # conflicting regex matches.
        bs_links: List[BuildSystemLink] = []
        if project_root is not None:
            readers = build_system_readers
            if readers is None:
                # Build the default reader registry from the active config's
                # build_systems block. The OpenTitan-flavored YAML enables
                # dvsim_hjson + bazel; in-process defaults stay all-off.
                from kgweave.knowledge_graph.common.sw_test_buildsys import (
                    default_readers as _default_readers,
                )

                bs_cfg = getattr(self._sw_test_config, "build_systems", None)
                readers = _default_readers(
                    bs_cfg, project_conventions=self._project_conventions
                )
            bs_links = discover_links(Path(project_root), readers=readers)

        # Index: (canonical_test_path) → list[BuildSystemLink]. We also
        # index by absolute string so callers passing absolute paths can
        # cross-reference. Test files are looked up by:
        #   - absolute resolved path
        #   - filename basename (e.g. ``aes_smoke.c``)
        #   - stem (e.g. ``aes_smoke``) — dvsim/UVM testnames typically
        #     omit the file suffix.
        bs_by_test: Dict[str, List[BuildSystemLink]] = {}
        for link in bs_links:
            try:
                key_abs = str(Path(link.test_path).resolve())
            except OSError:
                key_abs = link.test_path
            bs_by_test.setdefault(key_abs, []).append(link)
            bn = Path(link.test_path).name
            bs_by_test.setdefault(bn, []).append(link)
            stem = Path(link.test_path).stem
            if stem and stem != bn:
                bs_by_test.setdefault(stem, []).append(link)

        entities: List[Entity] = []
        triples: List[Triple] = []

        for c_path in c_files:
            self._process_file(c_path, entities, triples, bs_by_test)

        return ExtractionResult(entities=entities, triples=triples)

    def _process_file(
        self,
        c_path: Path,
        entities: List[Entity],
        triples: List[Triple],
        bs_by_test: Optional[Dict[str, List[BuildSystemLink]]] = None,
    ) -> None:
        """Process one C test file: emit SW_Test + tests_module + accesses_csr.

        ``bs_by_test`` (Tier B): mapping from test path (abs or basename)
        to the list of build-system links covering that file. Modules
        named in those links are emitted with build-system provenance
        and *suppress* any regex match for the same module.
        """
        test_name = c_path.stem
        bs_links_here: List[BuildSystemLink] = []
        if bs_by_test:
            try:
                key_abs = str(c_path.resolve())
            except OSError:
                key_abs = str(c_path)
            for key in (key_abs, c_path.name, c_path.stem):
                if key and key in bs_by_test:
                    bs_links_here.extend(bs_by_test[key])
        # Dedup links on (module_name, source_format, source_file).
        seen_link_keys = set()
        deduped_links: List[BuildSystemLink] = []
        for link in bs_links_here:
            k = (link.module_name, link.source_format, link.source_file)
            if k in seen_link_keys:
                continue
            seen_link_keys.add(k)
            deduped_links.append(link)
        bs_links_here = deduped_links

        # Modules already covered by a build-system link → regex matches
        # suppressed. Only canonical (resolvable) modules go in this set.
        bs_covered_modules: Set[str] = set()
        for link in bs_links_here:
            resolved = self._claim_index.resolve(link.module_name)
            if resolved:
                bs_covered_modules.add(resolved)

        try:
            text = c_path.read_text(errors="replace")
        except Exception as exc:
            _logger.warning("Could not read %s: %s", c_path, exc)
            entities.append(Entity(
                name=test_name,
                type="SW_Test",
                sources=[str(c_path)],
                extractor_source=[SW_TEST_SOURCE],
                layer=SW_TEST_SOURCE,
                is_test=None,
            ))
            return

        is_test = any(
            marker.search(text) is not None
            for marker in self._sw_test_config.test_markers
        )
        entities.append(Entity(
            name=test_name,
            type="SW_Test",
            sources=[str(c_path)],
            extractor_source=[SW_TEST_SOURCE],
            layer=SW_TEST_SOURCE,
            is_test=is_test,
        ))

        # Config-driven pattern engine. Per (test, module) tuple we emit at
        # most one edge; the first pattern (in declaration order) that
        # claims the module owns the edge — its tier and evidence are
        # used. Subsequent patterns matching the same module contribute
        # additional evidence-span fragments.
        # module_name → {tier, pattern_name, evidence: List[str]}
        module_evidence: Dict[str, Dict[str, Any]] = {}
        # Per-pattern modules resolved (used for the dif_api_call synthetic
        # CSR side-effect that preserves Tier-2 OpenTitan behavior).
        per_pattern_modules: Dict[str, Set[str]] = {}

        for pattern in self._sw_test_config.patterns:
            seen_in_pattern: Set[str] = set()
            for m in pattern.regex.finditer(text):
                try:
                    captured = m.group("module")
                except IndexError:
                    continue
                if not captured:
                    continue
                normalized = pattern.apply_transform(captured)
                resolved = self._claim_index.resolve(normalized)
                if not resolved:
                    continue
                if resolved in seen_in_pattern:
                    continue
                seen_in_pattern.add(resolved)
                # Tier B precedence: build-system link wins. Skip regex
                # match emission when the module is already covered by a
                # build-system link. (We still record it under
                # per_pattern_modules so the dif_api_call synthetic CSR
                # side-effect remains available — that synthetic is a
                # different signal entirely.)
                if resolved in bs_covered_modules:
                    continue
                evidence_fragment = self._format_evidence(pattern.name, m)
                if resolved not in module_evidence:
                    module_evidence[resolved] = {
                        "tier": pattern.confidence_tier,
                        "pattern": pattern.name,
                        "evidence": [evidence_fragment],
                    }
                else:
                    module_evidence[resolved]["evidence"].append(evidence_fragment)
            per_pattern_modules[pattern.name] = seen_in_pattern

        # Tier B: emit build-system links first (one per resolved module).
        # bs_emitted_modules tracks canonical names already covered to
        # dedup multiple links to the same module within this file.
        bs_emitted_modules: Set[str] = set()
        for link in bs_links_here:
            resolved = self._claim_index.resolve(link.module_name)
            if not resolved or resolved in bs_emitted_modules:
                continue
            bs_emitted_modules.add(resolved)
            triples.append(Triple(
                subject=test_name,
                predicate="tests_module",
                object=resolved,
                source=str(c_path),
                extractor_source=SW_TEST_SOURCE,
                evidence_span=(
                    f"{link.source_format}:{Path(link.source_file).name} "
                    f"-> {resolved} in {c_path.name}"
                ),
                layer=SW_TEST_SOURCE,
                confidence_tier=link.confidence_tier,
                resolved=True,
                attributes={
                    "build_system_source": link.source_file,
                    "build_system_format": link.source_format,
                },
            ))

        # Emit one deduplicated tests_module edge per resolved module.
        for mod in sorted(module_evidence):
            info = module_evidence[mod]
            evidence = " | ".join(info["evidence"])
            triples.append(Triple(
                subject=test_name,
                predicate="tests_module",
                object=mod,
                source=str(c_path),
                extractor_source=SW_TEST_SOURCE,
                evidence_span=f"{evidence} in {c_path.name}",
                layer=SW_TEST_SOURCE,
                confidence_tier=info["tier"],
                resolved=True,
            ))

        tests_module_resolved = bool(module_evidence) or bool(bs_emitted_modules)

        # Real test with no resolution → low-tier unresolved sentinel edge.
        if is_test and not tests_module_resolved:
            triples.append(Triple(
                subject=test_name,
                predicate="tests_module",
                object="<unknown>",
                source=str(c_path),
                extractor_source=SW_TEST_SOURCE,
                evidence_span=f"test detected in {c_path.name} but no module resolved",
                layer=SW_TEST_SOURCE,
                confidence_tier="low",
                resolved=False,
            ))

        # accesses_csr emission (orthogonal to tests_module work).
        csr_names: Set[str] = set()

        if self._mmio_re is not None:
            for m in self._mmio_re.finditer(text):
                csr = self._offset_to_csr(m.group(1))
                if csr:
                    csr_names.add(csr)

        if self._bare_offset_re is not None:
            for m in self._bare_offset_re.finditer(text):
                csr = self._offset_to_csr(m.group(1))
                if csr:
                    csr_names.add(csr)

        # Synthetic CSR access from a configured pattern name. Tier-2 heuristic
        # preserved for OT (pattern name "dif_api_call"); generic profiles
        # leave ``synthetic_csr_from_pattern=None`` and produce no synthesis.
        if self._synthetic_csr_pattern:
            synth_modules = per_pattern_modules.get(self._synthetic_csr_pattern, set())
            for canonical_module in synth_modules:
                module_lower = canonical_module.lower()
                synthetic = (
                    f"{canonical_module}.{module_lower}_{self._synthetic_csr_pattern}"
                )
                csr_names.add(synthetic)

        for csr_name in sorted(csr_names):
            triples.append(Triple(
                subject=test_name,
                predicate="accesses_csr",
                object=csr_name,
                source=str(c_path),
                extractor_source=SW_TEST_SOURCE,
                evidence_span=f"CSR access in {c_path.name}",
                layer=SW_TEST_SOURCE,
            ))

    def _format_evidence(self, pattern_name: str, m: re.Match) -> str:
        """Render a short evidence string for a pattern match.

        Mirrors the pre-refactor evidence vocabulary so existing audits
        and snapshots stay readable.
        """
        if pattern_name == "header_include":
            tpl = getattr(self, "_evidence_include_tpl", None)
            if tpl:
                try:
                    module = m.group("module")
                except IndexError:
                    module = "?"
                try:
                    return tpl.format(module=module)
                except (KeyError, IndexError):
                    return tpl
            return pattern_name
        if pattern_name == (self._synthetic_csr_pattern or OPENTITAN_DIF_PATTERN_NAME):
            tpl = getattr(self, "_evidence_call_tpl", None)
            if tpl:
                try:
                    module = m.group("module")
                except IndexError:
                    module = "?"
                try:
                    return tpl.format(module=module)
                except (KeyError, IndexError):
                    return tpl
            return pattern_name
        # Generic evidence: full match text.
        return m.group(0)

    def _offset_to_csr(self, offset_const: str) -> Optional[str]:
        """Map an offset constant like ``AES_CTRL_SHADOWED_REG_OFFSET`` to a CSR name."""
        name = offset_const
        # Iterate longer suffixes first so e.g. ``_REG_OFFSET`` strips fully
        # before the bare ``_OFFSET`` is considered.
        for suffix in sorted(self._csr_offset_suffixes, key=len, reverse=True):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break

        parts = name.split("_", 1)
        if len(parts) < 2:
            return None
        module_part = parts[0].lower()
        reg_part = parts[1].lower()

        candidate = f"{module_part}.{reg_part}"
        canonical = self._known_lower.get(candidate)
        if canonical:
            return canonical

        return candidate
