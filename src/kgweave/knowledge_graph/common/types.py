# @summary
# Configuration types and YAML schema loader for the KG subsystem.
# Exports: NodeTypeDefinition, EdgeTypeDefinition, SchemaDefinition, KGConfig, load_schema
# Deps: dataclasses, typing, yaml, logging
# New retrieval fields on KGConfig: retrieval_edge_types, retrieval_path_patterns,
#   graph_context_token_budget, enable_graph_context_injection (REQ-KG-1200..1206),
#   strict_path_validation (REQ-KG-778)
# @end-summary
"""Configuration and schema types for the KG subsystem.

Provides typed dataclasses for KG configuration (``KGConfig``) and the parsed
YAML schema (``SchemaDefinition``), plus the ``load_schema()`` loader that
validates and deserialises ``config/kg_schema.yaml``.
"""

from __future__ import annotations

import logging
import os
import warnings

import yaml

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from kgweave.knowledge_graph.common.sw_test_config import SwTestPattern

__all__ = [
    "NodeTypeDefinition",
    "EdgeTypeDefinition",
    "SchemaDefinition",
    "ProjectConventions",
    "OPENTITAN_PROFILE",
    "KGConfig",
    "load_schema",
]

_schema_logger = logging.getLogger("rag.knowledge_graph.schema")

VALID_CATEGORIES = {"structural", "semantic", "claim"}

#: Canonical profile identifier for the OpenTitan project.  All
#: ``profile == "opentitan"`` comparisons in extractors must reference
#: this constant rather than a bare string literal.
OPENTITAN_PROFILE: str = "opentitan"
VALID_PHASES = {"phase_1", "phase_1b", "phase_2"}


@dataclass
class NodeTypeDefinition:
    """Schema definition for a single node type.

    Attributes:
        name: Unique identifier for this node type (e.g. ``RTL_Module``).
        description: Human-readable description of what this type represents.
        category: Either ``"structural"`` (parser-extracted) or ``"semantic"`` (LLM-extracted).
        phase: Earliest runtime phase at which this type is active.
        gliner_label: Optional label string passed to GLiNER NER model.
        extraction_hints: Optional free-text hints for LLM extraction prompts.
    """

    name: str
    description: str
    category: str       # "structural" | "semantic"
    phase: str          # "phase_1" | "phase_1b" | "phase_2"
    gliner_label: Optional[str] = None
    extraction_hints: Optional[str] = None


@dataclass
class EdgeTypeDefinition:
    """Schema definition for a single edge (relationship) type.

    Attributes:
        name: Unique identifier for this edge type (e.g. ``instantiates``).
        description: Human-readable description of the relationship.
        category: Either ``"structural"`` or ``"semantic"``.
        phase: Earliest runtime phase at which this edge type is active.
        source_types: Node types that may appear as the subject.
        target_types: Node types that may appear as the object.
    """

    name: str
    description: str
    category: str
    phase: str
    source_types: List[str] = field(default_factory=list)
    target_types: List[str] = field(default_factory=list)


@dataclass
class SchemaDefinition:
    """Parsed and validated KG schema from ``config/kg_schema.yaml``.

    Attributes:
        version: Schema version string (e.g. ``"1.0"``).
        description: Free-text description of the schema.
        node_types: Ordered list of node type definitions.
        edge_types: Ordered list of edge type definitions.
    """

    version: str
    description: str
    node_types: List[NodeTypeDefinition] = field(default_factory=list)
    edge_types: List[EdgeTypeDefinition] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._node_index: Dict[str, NodeTypeDefinition] = {n.name: n for n in self.node_types}
        self._edge_index: Dict[str, EdgeTypeDefinition] = {e.name: e for e in self.edge_types}

    def active_node_types(self, runtime_phase: str) -> List[NodeTypeDefinition]:
        """Return node types active for *runtime_phase* (phase-ordered subset)."""
        from kgweave.knowledge_graph.common.utils import is_phase_active
        return [n for n in self.node_types if is_phase_active(n.phase, runtime_phase)]

    def active_edge_types(self, runtime_phase: str) -> List[EdgeTypeDefinition]:
        """Return edge types active for *runtime_phase* (phase-ordered subset)."""
        from kgweave.knowledge_graph.common.utils import is_phase_active
        return [e for e in self.edge_types if is_phase_active(e.phase, runtime_phase)]

    def is_valid_node_type(self, type_name: str, runtime_phase: str) -> bool:
        """Return True if *type_name* exists in the schema and is active for the runtime phase."""
        if type_name not in self._node_index:
            return False
        from kgweave.knowledge_graph.common.utils import is_phase_active
        return is_phase_active(self._node_index[type_name].phase, runtime_phase)

    def is_valid_edge_type(self, type_name: str, runtime_phase: str) -> bool:
        """Return True if *type_name* exists in the schema and is active for the runtime phase."""
        if type_name not in self._edge_index:
            return False
        from kgweave.knowledge_graph.common.utils import is_phase_active
        return is_phase_active(self._edge_index[type_name].phase, runtime_phase)


@dataclass
class ProjectConventions:
    """Project-shaped conventions consumed by extractors and readers.

    Phase 1 scaffolding only — this dataclass is constructed and round-tripped
    through ``KGConfig`` but no consumer reads from it yet. Phase 2 wires
    extractors and readers to consult these fields in lieu of their own
    OT-flavored hardcoded defaults.

    Treat this dataclass as effectively read-only after construction:
    consumers must only *read* fields. Use ``ProjectConventions.opentitan()``
    to obtain the OT-shaped back-compat profile; bare ``ProjectConventions()``
    yields strict-generic defaults (most fields ``None``).
    """

    # --- Identity / opt-in profile selection ---
    profile: Optional[str] = None
    """``"opentitan"`` selects the OT profile via ``ProjectConventions.opentitan()``;
    ``None`` means strict-generic mode (no OT-specific fallbacks)."""

    # --- SV connectivity ---
    reset_signal_pattern: Optional[str] = None
    """Regex (case-insensitive) classifying always_ff sensitivity-list signals
    as resets vs clocks. ``None`` means consumer falls back to its own default."""

    clock_signal_pattern: Optional[str] = None
    """Optional positive-match regex for clock identifier names. ``None`` means
    treat the non-reset sensitivity-list entry as the clock."""

    # --- Testplan / SVA ---
    sva_prefixes: Optional[List[str]] = None
    """Override prefixes for SVA assertion-name normalisation. ``None`` keeps
    consumer defaults."""

    sva_suffixes: Optional[List[str]] = None
    """Override suffixes for SVA assertion-name normalisation."""

    # --- SW test resolution ---
    sw_test_patterns: Optional[List["SwTestPattern"]] = None
    """List of ``SwTestPattern`` entries mapping SW source patterns to module
    names. Phase 1 leaves this ``None``; Phase 2 wires patterns through."""

    sw_test_markers: Optional[List[str]] = None
    """Marker substrings indicating that a C/C++ source file is a test entry."""

    csr_access_api_patterns: Optional[List[str]] = None
    """Regexes matching MMIO/CSR access API call sites
    (e.g. ``mmio_region_write32``, ``abs_mmio_*``)."""

    csr_offset_suffixes: List[str] = field(
        default_factory=lambda: ["_REG_OFFSET", "_OFFSET"]
    )
    """Suffixes identifying CSR offset macros referenced in SW tests."""

    sw_test_extensions: List[str] = field(default_factory=lambda: [".c"])
    """File extensions to scan when walking SW test directories."""

    synthetic_csr_from_pattern: Optional[str] = None
    """When set, emit a synthetic ``<mod>_dif_access`` CSR side-effect for
    sources matching this pattern name. ``None`` disables synthesis."""

    evidence_format_include_template: Optional[str] = None
    """Optional ``str.format`` template (``{module}`` placeholder) used to
    render evidence text for ``header_include`` pattern matches. ``None``
    falls back to using the bare pattern name as evidence text."""

    evidence_format_call_template: Optional[str] = None
    """Optional ``str.format`` template (``{module}`` placeholder) used to
    render evidence text for the synthetic-CSR call pattern. ``None`` falls
    back to using the bare pattern name as evidence text."""

    # --- Build-system readers ---
    bazel_rule_allowlist: Optional[List[str]] = None
    """Bazel rule kinds that count as test/binary entries."""

    bazel_dep_module_pattern: Optional[str] = None
    """Regex with named ``module`` group used to extract module names from
    Bazel ``//hw/ip/<mod>:...``-style deps. ``None`` disables module
    inference for Bazel readers."""

    bazel_srcs_default_extensions: Optional[List[str]] = None
    """Filename extensions used to synthesize a fallback ``srcs`` list when
    a Bazel rule has ``name`` but no ``srcs`` attribute (e.g. ``[".c"]``).
    ``None`` means do not synthesize — skip emission for rules without
    explicit ``srcs``."""

    makefile_module_vars: List[str] = field(
        default_factory=lambda: ["MODULE", "IP_NAME", "IP_TOP", "DUT", "DUT_NAME"]
    )
    """Makefile variable names whose values are treated as the module name."""

    makefile_test_target_prefixes: List[str] = field(
        default_factory=lambda: ["test-", "test_"]
    )
    """Prefixes recognised on Makefile test targets (e.g. ``test-aes:``)."""

    makefile_module_strip_suffixes: List[str] = field(
        default_factory=lambda: ["_top", "_dut", "_core", "_wrapper"]
    )
    """Suffixes stripped from Makefile module values to canonicalise."""

    fusesoc_tb_target_hints: List[str] = field(
        default_factory=lambda: ["sim", "tb", "test"]
    )
    """Substrings identifying FuseSoC testbench targets."""

    fusesoc_module_strip_suffixes: List[str] = field(
        default_factory=lambda: ["_sim", "_tb", "_test", "_dv"]
    )
    """Suffixes stripped from FuseSoC ``.core`` names to derive module."""

    uvm_testbench_filename_regex: str = r"([A-Za-z_]\w*)_tb\.sv"
    """Regex extracting module name from a UVM testbench filename."""

    # --- DV file→testplan fusion ---
    dv_test_file_strip_suffixes: List[str] = field(
        default_factory=lambda: ["_vseq.sv", "_test.sv", ".sv"]
    )
    """Suffixes stripped from DV test source filenames during testplan fusion."""

    @classmethod
    def opentitan(cls) -> "ProjectConventions":
        """Return a ProjectConventions instance pre-populated with OpenTitan
        defaults — back-compat entry point for the current OT-shaped pipeline.

        Phase 1 sets the OT-flavoured fields on this profile but does NOT
        populate ``sw_test_patterns`` (Phase 2 wires the actual patterns from
        ``sw_test_config``).
        """
        return cls(
            profile="opentitan",
            reset_signal_pattern=r"(^|_)(rst|reset|por)(_|$)",
            sva_prefixes=["a_", "prim_", "aes_"],
            sw_test_patterns=None,  # Phase 2: wire from sw_test_config
            bazel_rule_allowlist=[
                "opentitan_functest",
                "opentitan_test",
                "opentitan_binary",
                "cc_test",
                "cc_binary",
                "dv_lib",
                "dv_fusesoc_test",
            ],
            bazel_dep_module_pattern=r"^//hw/ip/(?P<module>[a-z][a-z0-9_]*)\b",
            bazel_srcs_default_extensions=[".c"],
            synthetic_csr_from_pattern="dif_api_call",
            evidence_format_include_template='#include "dif_{module}.h"',
            evidence_format_call_template="dif_{module}_* call",
            sw_test_markers=[
                r"\bint\s+main\s*\(",
                r"\bvoid\s+test_main\s*\(",
                r"\bOTTF_DEFINE_TEST_CONFIG\b",
            ],
        )


@dataclass
class KGConfig:
    """Runtime configuration for the knowledge graph subsystem.

    All fields have sane defaults suitable for a Phase 1, NetworkX-backed,
    regex-only extraction run.

    Attributes:
        backend: Storage backend name — ``"networkx"`` (default) or ``"neo4j"``.
        schema_path: Path to the KG schema YAML file.
        enable_regex_extractor: Enable lightweight regex-based extraction.
        enable_gliner_extractor: Enable GLiNER NER-based extraction.
        enable_llm_extractor: Enable LLM structured-output extraction.
        enable_sv_parser: Enable tree-sitter-verilog parser extraction.
        entity_description_token_budget: Max tokens for accumulated entity descriptions.
        entity_description_top_k_mentions: Max raw mentions kept per entity.
        max_expansion_depth: Hop depth for KG-based query expansion.
        max_expansion_terms: Maximum additional terms injected by expansion.
        enable_llm_query_fallback: Enable LLM fallback for entity matching.
        llm_fallback_timeout_ms: Wall-clock budget for the LLM fallback in ms.
        enable_global_retrieval: Enable community-summary global retrieval (Phase 2).
        runtime_phase: Active schema phase — ``"phase_1"``, ``"phase_1b"``, or ``"phase_2"``.
        regex_fallback_type: Node type assigned to regex-extracted entities lacking a known type.
        extractor_priority: Ordered list of extractor names (first = highest priority).
    """

    backend: str = "networkx"
    schema_path: str = "config/kg_schema.yaml"
    enable_regex_extractor: bool = True
    enable_gliner_extractor: bool = False
    enable_llm_extractor: bool = False
    enable_sv_parser: bool = False
    entity_description_token_budget: int = 512
    entity_description_top_k_mentions: int = 5
    max_expansion_depth: int = 1
    max_expansion_terms: int = 3
    enable_llm_query_fallback: bool = False
    llm_fallback_timeout_ms: int = 1000
    enable_global_retrieval: bool = False
    runtime_phase: str = "phase_1"
    regex_fallback_type: str = "concept"
    extractor_priority: List[str] = field(
        default_factory=lambda: ["sv_parser", "llm", "gliner", "regex"]
    )
    # Phase 1b: LLM extractor settings
    llm_extraction_model: str = "default"  # LLMProvider model alias
    llm_extraction_prompt_template: Optional[str] = None  # file path override
    llm_extraction_max_retries: int = 1
    llm_extraction_temperature: float = 0.1  # low temp for structured output

    # Phase 2: Community detection
    community_resolution: float = 1.0
    """Leiden resolution parameter. Higher = more, smaller communities."""
    community_min_size: int = 3
    """Minimum entities per community; smaller clusters merge to community_id=-1."""

    # Phase 2: Community summarization
    community_summary_input_max_tokens: int = 4096
    """Max token budget for concatenated entity descriptions in LLM prompt."""
    community_summary_output_max_tokens: int = 512
    """max_tokens passed to LLM call for summary generation."""
    community_summary_temperature: float = 0.2
    """LLM temperature for community summarization calls."""
    community_summary_max_workers: int = 4
    """ThreadPoolExecutor worker count for parallel summarization."""

    # Phase 2: Neo4j backend — defaults consult env so dataclass instances
    # built without explicit overrides still honour deployment configuration.
    neo4j_uri: str = field(
        default_factory=lambda: os.environ.get("RAG_KG_NEO4J_URI", "bolt://localhost:7687")
    )
    neo4j_auth_user: str = field(
        default_factory=lambda: os.environ.get("RAG_KG_NEO4J_AUTH_USER", "neo4j")
    )
    neo4j_auth_password: str = field(
        default_factory=lambda: os.environ.get("RAG_KG_NEO4J_AUTH_PASSWORD", ""),
        repr=False,
    )
    neo4j_database: str = field(
        default_factory=lambda: os.environ.get("RAG_KG_NEO4J_DATABASE", "neo4j")
    )

    # Phase 2: Optional parsers
    enable_python_parser: bool = False
    enable_bash_parser: bool = False

    # Phase 2: Graph path (used by sidecar persistence)
    graph_path: Optional[str] = None

    # Phase 3: SV port connectivity
    sv_filelist: str = ""
    """Newline-separated list of .sv/.v file paths for dataflow analysis."""
    sv_top_module: str = ""
    """Top-level module name passed to the pyslang elaborator."""

    enable_ast_decomposition: bool = True
    """Wave 2 / v2: gate v2 AST-layer emission (Operator/Literal/Index/
    IfStatement/CaseStatement/Loop/Branch/Assignment/Condition + structural
    edges, all tagged ``layer="ast"``).

    Default ``True`` — the demo and audit pipelines benefit from the richer
    decomposition, and the AST layer is hidden from default consumer views
    via ``subgraph_by_layer`` / ``entities_by_layer`` filters. Cost-sensitive
    consumers (sigma export at scale, lightweight indexers) can disable to
    fall back to the v1 graph shape."""

    # Phase 3: Entity resolution
    enable_entity_resolution: bool = False
    """Enable embedding-based entity deduplication and alias merging."""
    entity_resolution_threshold: float = 0.85
    """Cosine similarity threshold above which two entities are merged."""
    entity_resolution_alias_path: str = "config/kg_aliases.yaml"
    """Path to a YAML file containing manual alias mappings."""

    # Phase 3: Hierarchical Leiden
    community_max_levels: int = 3
    """Maximum recursion depth for hierarchical Leiden community detection."""

    # Retrieval enhancements
    retrieval_edge_types: List[str] = field(default_factory=list)
    """REQ-KG-1200: Edge type whitelist for typed traversal. Empty = untyped."""

    retrieval_path_patterns: List[List[str]] = field(default_factory=list)
    """REQ-KG-1202: Ordered edge type sequences for path pattern matching."""

    graph_context_token_budget: int = 500
    """REQ-KG-1204: Max tokens for graph context block in generation prompt."""

    enable_graph_context_injection: bool = False
    """REQ-KG-1206: Master toggle. False = skip all retrieval enhancements."""

    strict_path_validation: bool = False
    """REQ-KG-778: When True, PatternWarning promoted to KGConfigValidationError."""

    # Phase 2 Retrieval: Community context + operator configurability (REQ-KG-1320..1326)
    community_context_token_budget: int = 200
    """REQ-KG-1320: Independent token budget for community context section. 0 = disabled."""

    graph_context_marker_style: str = "markdown"
    """REQ-KG-1322: Section marker style — 'markdown', 'xml', or 'plain'."""

    max_hop_fanout: int = 50
    """REQ-KG-1324: Max entities explored per hop in path pattern evaluation."""

    # V3 #7: portability — reset/clock disambiguation in always_ff sensitivity
    # lists. ``SlangHierarchyAnalyzer`` falls back to a built-in OT-flavored
    # default (``(^|_)(rst|reset|por)(_|$)``) when this is empty/None. Set to
    # a custom Python regex (str) to match codebases using non-OT reset
    # naming conventions (``aresetn``, ``nrst``, ``srst_n``, ...).
    reset_signal_pattern: Optional[str] = None
    """Regex (case-insensitive) classifying always_ff sensitivity-list signals
    as resets vs. clocks. ``None`` keeps the OT-default heuristic."""

    # V3 #7: portability — testplan SVA name normalization. Default OT-flavored
    # prefix list (``a_``, ``prim_``, ``aes_``) is augmented but never reduced
    # by user input so OT behaviour is preserved.
    testplan_sva_prefixes: Optional[List[str]] = None
    """Extra/override prefixes for SVA assertion-name normalisation in
    ``TestplanExtractor``. ``None`` keeps the OT default
    ``("a_", "prim_", "aes_")``."""

    # Phase 1 hardcoded-values cleanup: consolidated project conventions.
    # Each KGConfig instance gets a fresh ProjectConventions(); the legacy
    # ``reset_signal_pattern`` and ``testplan_sva_prefixes`` fields above are
    # deprecation shims that copy through into this dataclass when set without
    # an explicit ``project_conventions`` overlay (see ``__post_init__``).
    project_conventions: "ProjectConventions" = field(default_factory=lambda: ProjectConventions())
    """Consolidated project-shaped conventions consumed by extractors and
    readers. Phase 1 wires only the dataclass; Phase 2 wires consumers."""

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "KGConfig":
        """Build a ``KGConfig`` from environment variables.

        Reads ``RAG_KG_*`` variables directly from *env* (defaults to
        ``os.environ``). Any variable that is unset falls back to the
        dataclass default. This method is the canonical KG config loader and
        contains no dependency on ``config.settings`` — making the package
        portable to KGWeave without modification.

        Args:
            env: Optional mapping to read from. Useful for tests. When
                ``None``, reads from ``os.environ``.

        Returns:
            A populated ``KGConfig`` instance.
        """
        e = env if env is not None else os.environ

        def _str(key: str, default: str) -> str:
            return e.get(key, default)

        def _int(key: str, default: int) -> int:
            raw = e.get(key)
            return int(raw) if raw is not None and raw != "" else default

        def _float(key: str, default: float) -> float:
            raw = e.get(key)
            return float(raw) if raw is not None and raw != "" else default

        def _bool(key: str, default: bool) -> bool:
            raw = e.get(key)
            if raw is None or raw == "":
                return default
            return raw.lower() in ("true", "1", "yes", "on")

        def _str_list(key: str, sep: str = ",") -> List[str]:
            raw = e.get(key, "")
            return [t.strip() for t in raw.split(sep) if t.strip()]

        def _json_list(key: str, default: List) -> List:
            raw = e.get(key)
            if raw is None or raw == "":
                return default
            try:
                import json as _json
                value = _json.loads(raw)
                return value if isinstance(value, list) else default
            except (ValueError, TypeError):
                _schema_logger.warning(
                    "%s is not valid JSON; defaulting to %r", key, default
                )
                return default

        defaults = cls()  # gather field defaults via a throwaway instance

        cfg = cls(
            backend=_str("RAG_KG_BACKEND", defaults.backend),
            runtime_phase=_str("RAG_KG_RUNTIME_PHASE", defaults.runtime_phase),
            max_expansion_depth=_int("RAG_KG_MAX_EXPANSION_DEPTH", defaults.max_expansion_depth),
            max_expansion_terms=_int("RAG_KG_MAX_EXPANSION_TERMS", defaults.max_expansion_terms),
            entity_description_token_budget=_int(
                "RAG_KG_DESCRIPTION_TOKEN_BUDGET", defaults.entity_description_token_budget
            ),
            graph_path=e.get("RAG_KG_GRAPH_PATH", defaults.graph_path),
            # Phase 2: community detection
            enable_global_retrieval=_bool(
                "RAG_KG_ENABLE_GLOBAL_RETRIEVAL", defaults.enable_global_retrieval
            ),
            community_resolution=_float(
                "RAG_KG_COMMUNITY_RESOLUTION", defaults.community_resolution
            ),
            community_min_size=_int("RAG_KG_COMMUNITY_MIN_SIZE", defaults.community_min_size),
            community_summary_input_max_tokens=_int(
                "RAG_KG_COMMUNITY_SUMMARY_INPUT_MAX_TOKENS",
                defaults.community_summary_input_max_tokens,
            ),
            community_summary_output_max_tokens=_int(
                "RAG_KG_COMMUNITY_SUMMARY_OUTPUT_MAX_TOKENS",
                defaults.community_summary_output_max_tokens,
            ),
            community_summary_temperature=_float(
                "RAG_KG_COMMUNITY_SUMMARY_TEMPERATURE",
                defaults.community_summary_temperature,
            ),
            community_summary_max_workers=_int(
                "RAG_KG_COMMUNITY_SUMMARY_MAX_WORKERS",
                defaults.community_summary_max_workers,
            ),
            # Phase 2: Neo4j (defaults already env-aware via field default_factory)
            # Phase 2: Optional parsers
            enable_python_parser=_bool(
                "RAG_KG_ENABLE_PYTHON_PARSER", defaults.enable_python_parser
            ),
            enable_bash_parser=_bool(
                "RAG_KG_ENABLE_BASH_PARSER", defaults.enable_bash_parser
            ),
            # Phase 3: SV / entity resolution / hierarchical Leiden
            sv_filelist=_str("RAG_KG_SV_FILELIST", defaults.sv_filelist),
            sv_top_module=_str("RAG_KG_SV_TOP_MODULE", defaults.sv_top_module),
            enable_entity_resolution=_bool(
                "RAG_KG_ENABLE_ENTITY_RESOLUTION", defaults.enable_entity_resolution
            ),
            entity_resolution_threshold=_float(
                "RAG_KG_ENTITY_RESOLUTION_THRESHOLD", defaults.entity_resolution_threshold
            ),
            entity_resolution_alias_path=_str(
                "RAG_KG_ENTITY_RESOLUTION_ALIAS_PATH", defaults.entity_resolution_alias_path
            ),
            community_max_levels=_int(
                "RAG_KG_COMMUNITY_MAX_LEVELS", defaults.community_max_levels
            ),
            # Retrieval
            retrieval_edge_types=_str_list("RAG_KG_RETRIEVAL_EDGE_TYPES"),
            retrieval_path_patterns=_json_list("RAG_KG_RETRIEVAL_PATH_PATTERNS", []),
            graph_context_token_budget=_int(
                "RAG_KG_GRAPH_CONTEXT_TOKEN_BUDGET", defaults.graph_context_token_budget
            ),
            enable_graph_context_injection=_bool(
                "RAG_KG_ENABLE_GRAPH_CONTEXT_INJECTION",
                defaults.enable_graph_context_injection,
            ),
            community_context_token_budget=_int(
                "RAG_KG_COMMUNITY_CONTEXT_TOKEN_BUDGET",
                defaults.community_context_token_budget,
            ),
            graph_context_marker_style=_str(
                "RAG_KG_GRAPH_CONTEXT_MARKER_STYLE", defaults.graph_context_marker_style
            ),
            max_hop_fanout=_int("RAG_KG_MAX_HOP_FANOUT", defaults.max_hop_fanout),
            reset_signal_pattern=(
                e.get("RAG_KG_RESET_SIGNAL_PATTERN", defaults.reset_signal_pattern)
                or defaults.reset_signal_pattern
            ),
            testplan_sva_prefixes=(
                _str_list("RAG_KG_TESTPLAN_SVA_PREFIXES")
                or defaults.testplan_sva_prefixes
            ),
        )
        return cfg

    def __post_init__(self) -> None:
        if self.community_min_size < 1:
            raise ValueError(f"community_min_size must be >= 1, got {self.community_min_size}")
        if self.community_resolution <= 0:
            raise ValueError(f"community_resolution must be > 0, got {self.community_resolution}")
        if not (0.0 < self.entity_resolution_threshold <= 1.0):
            raise ValueError(
                f"entity_resolution_threshold must be in (0.0, 1.0], "
                f"got {self.entity_resolution_threshold}"
            )
        if self.community_max_levels < 1:
            raise ValueError(
                f"community_max_levels must be >= 1, got {self.community_max_levels}"
            )
        if self.graph_context_token_budget < 0:
            raise ValueError("graph_context_token_budget must be >= 0")
        if self.community_context_token_budget < 0:
            raise ValueError(
                f"community_context_token_budget must be >= 0, got {self.community_context_token_budget}"
            )
        if self.graph_context_marker_style not in {"markdown", "xml", "plain"}:
            raise ValueError(
                f"graph_context_marker_style must be 'markdown', 'xml', or 'plain', "
                f"got '{self.graph_context_marker_style}'"
            )
        if self.max_hop_fanout < 1:
            raise ValueError(f"max_hop_fanout must be >= 1, got {self.max_hop_fanout}")

        # --- Phase 1 deprecation shims: legacy KGConfig fields → ProjectConventions ---
        if (
            self.reset_signal_pattern is not None
            and self.project_conventions.reset_signal_pattern is None
        ):
            warnings.warn(
                "KGConfig.reset_signal_pattern is deprecated; "
                "use KGConfig.project_conventions.reset_signal_pattern instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self.project_conventions.reset_signal_pattern = self.reset_signal_pattern

        if (
            self.testplan_sva_prefixes is not None
            and self.project_conventions.sva_prefixes is None
        ):
            warnings.warn(
                "KGConfig.testplan_sva_prefixes is deprecated; "
                "use KGConfig.project_conventions.sva_prefixes instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self.project_conventions.sva_prefixes = list(self.testplan_sva_prefixes)


# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------


def load_schema(path: str) -> SchemaDefinition:
    """Load and validate ``config/kg_schema.yaml`` from *path*.

    Algorithm
    ---------
    1. Open the YAML file with ``yaml.safe_load()``. Raise ``FileNotFoundError``
       if the file is missing.
    2. Parse ``node_types``: construct a ``NodeTypeDefinition`` for each entry.
       Required fields: ``name``, ``description``, ``category``, ``phase``.
       Optional: ``gliner_label``, ``extraction_hints``.
    3. Parse ``edge_types``: construct an ``EdgeTypeDefinition`` for each entry.
       Required fields: ``name``, ``description``, ``category``, ``phase``.
       Optional: ``source_types``, ``target_types``.
    4. Raise ``ValueError`` for any of:
       - Duplicate ``name`` values within ``node_types`` or ``edge_types``.
       - ``category`` not in ``{"structural", "semantic"}``.
       - ``phase`` not in ``{"phase_1", "phase_1b", "phase_2"}``.
       - Duplicate ``gliner_label`` values (among non-None labels).
    5. Log warnings for ``gliner_label`` values that collide with another
       type's ``name`` (ambiguous but not an error).
    6. Return ``SchemaDefinition``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the YAML fails any validation check.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except FileNotFoundError:
        raise FileNotFoundError(f"KG schema file not found: {path}")

    version = str(raw.get("version", "1.0"))
    description = str(raw.get("description", ""))

    # --- flatten nested YAML structure if needed ---
    # The YAML may use either:
    #   A) flat list:   node_types: [{name: X, ...}, ...]
    #   B) nested dict: node_types: {structural: {X: {...}, ...}, semantic: {...}}
    # Normalize to flat list form.
    def _flatten_typed_section(section) -> List[dict]:
        if isinstance(section, list):
            return section
        if isinstance(section, dict):
            flat: List[dict] = []
            for category_or_name, value in section.items():
                if isinstance(value, dict) and "description" in value:
                    # Direct entry: {TypeName: {description: ..., ...}}
                    flat.append({"name": category_or_name, **value})
                elif isinstance(value, dict):
                    # Category grouping: {structural: {TypeName: {...}, ...}}
                    for type_name, type_def in value.items():
                        if isinstance(type_def, dict):
                            flat.append({"name": type_name, **type_def})
            return flat
        return []

    # --- node types ---------------------------------------------------------
    node_names_seen: set[str] = set()
    gliner_labels_seen: set[str] = set()
    node_types: List[NodeTypeDefinition] = []

    for entry in _flatten_typed_section(raw.get("node_types", [])):
        name = entry["name"]
        if name in node_names_seen:
            raise ValueError(f"Duplicate node type name: '{name}'")
        node_names_seen.add(name)

        category = entry["category"]
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"Node type '{name}' has invalid category '{category}'. "
                f"Must be one of {VALID_CATEGORIES}."
            )

        phase = entry["phase"]
        if phase not in VALID_PHASES:
            raise ValueError(
                f"Node type '{name}' has invalid phase '{phase}'. "
                f"Must be one of {VALID_PHASES}."
            )

        gliner_label: Optional[str] = entry.get("gliner_label")
        if gliner_label is not None:
            if gliner_label in gliner_labels_seen:
                raise ValueError(f"Duplicate gliner_label '{gliner_label}' in node types.")
            gliner_labels_seen.add(gliner_label)

        node_types.append(
            NodeTypeDefinition(
                name=name,
                description=entry["description"],
                category=category,
                phase=phase,
                gliner_label=gliner_label,
                extraction_hints=entry.get("extraction_hints"),
            )
        )

    # --- edge types ---------------------------------------------------------
    edge_names_seen: set[str] = set()
    edge_types: List[EdgeTypeDefinition] = []

    for entry in _flatten_typed_section(raw.get("edge_types", [])):
        name = entry["name"]
        if name in edge_names_seen:
            raise ValueError(f"Duplicate edge type name: '{name}'")
        edge_names_seen.add(name)

        category = entry["category"]
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"Edge type '{name}' has invalid category '{category}'. "
                f"Must be one of {VALID_CATEGORIES}."
            )

        phase = entry["phase"]
        if phase not in VALID_PHASES:
            raise ValueError(
                f"Edge type '{name}' has invalid phase '{phase}'. "
                f"Must be one of {VALID_PHASES}."
            )

        edge_types.append(
            EdgeTypeDefinition(
                name=name,
                description=entry["description"],
                category=category,
                phase=phase,
                source_types=entry.get("source_types", []),
                target_types=entry.get("target_types", []),
            )
        )

    # --- cross-warnings: gliner_label collides with another type's name ----
    all_node_names = {n.name for n in node_types}
    for node in node_types:
        if (
            node.gliner_label is not None
            and node.gliner_label != node.name
            and node.gliner_label in all_node_names
        ):
            _schema_logger.warning(
                "Node type '%s' has gliner_label '%s' which collides with "
                "another type's name — this is ambiguous.",
                node.name,
                node.gliner_label,
            )

    return SchemaDefinition(
        version=version,
        description=description,
        node_types=node_types,
        edge_types=edge_types,
    )
