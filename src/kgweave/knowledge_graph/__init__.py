# @summary
# Public API for the knowledge graph subsystem: config-driven backend dispatcher
# and convenience functions. Re-exports common schemas for callers that need them.
# Exports: get_graph_backend, get_query_expander, export_obsidian,
#          GraphStorageBackend, GraphQueryExpander, KGConfig,
#          Entity, Triple, ExtractionResult, EntityDescription,
#          CommunitySummary, CommunityDiff
# Deps: src.knowledge_graph.backend, src.knowledge_graph.backends.*,
#       src.knowledge_graph.query.*, src.knowledge_graph.community.*,
#       src.knowledge_graph.export.obsidian, src.knowledge_graph.common.protocols
# Config loaded via KGConfig.from_env() — no dependency on config.settings.
# Retrieval settings (REQ-KG-1200..1206) read from RAG_KG_* env vars.
# Retrieval config validated at startup via common.validation (REQ-KG-1208).
# get_query_expander passes full KGConfig to GraphQueryExpander (REQ-KG-762) so
# typed traversal dispatch is available.
# @end-summary
"""Public API for the knowledge graph subsystem.

The retrieval and ingestion pipelines import only from this module.
Backend selection is controlled by configuration — changing the config
is all that is needed to swap graph storage implementations.

Dispatcher pattern:
    ``get_graph_backend()`` is a lazy singleton that constructs the
    configured backend on first call.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from kgweave.knowledge_graph.backend import GraphStorageBackend
from kgweave.knowledge_graph.common import (
    Entity,
    EntityDescription,
    ExtractionResult,
    Triple,
)
from kgweave.knowledge_graph.common import KGConfig
from kgweave.knowledge_graph.common.protocols import (
    KGAdminClient,
    KGIngestClient,
    KGIngestResult,
    set_default_llm_factory,
)
from kgweave.knowledge_graph.ingest_client import KGBuilderIngestClient

logger = logging.getLogger("rag.knowledge_graph")

# Process-wide singletons
_graph_backend: Optional[GraphStorageBackend] = None
_kg_config: Optional[KGConfig] = None


def _register_default_llm_factory() -> None:
    """Bind RagWeave's LLMProvider as the default LLM client for KG.

    Runs once on facade import. After the KGWeave extraction the host
    application registers its own factory; this in-tree registration
    preserves current behavior without forcing every KG node to import
    ``src.platform.llm`` directly.
    """
    try:
        from src.platform.llm import get_llm_provider  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("kg_default_llm_factory_unavailable error=%s", exc)
        return
    set_default_llm_factory(get_llm_provider)


_register_default_llm_factory()


def _build_kg_config() -> KGConfig:
    """Return the cached KG config, building from env on first call.

    Delegates to ``KGConfig.from_env()`` (the package-owned env loader) and
    runs RagWeave-specific startup validation. KGWeave will inherit the
    loader unchanged; only this in-tree validation hook stays here.
    """
    global _kg_config
    if _kg_config is not None:
        return _kg_config

    _kg_config = KGConfig.from_env()

    # Validate retrieval config at startup (REQ-KG-1208)
    if _kg_config.enable_graph_context_injection:
        try:
            from kgweave.knowledge_graph.common.validation import (
                validate_edge_types,
                validate_path_patterns,
            )
            if _kg_config.retrieval_edge_types:
                validate_edge_types(
                    _kg_config.retrieval_edge_types,
                    _kg_config.schema_path,
                )
            if _kg_config.retrieval_path_patterns:
                warnings = validate_path_patterns(
                    _kg_config.retrieval_path_patterns,
                    _kg_config.schema_path,
                )
                for w in warnings:
                    logger.warning("Path pattern validation: %s", w.message)
        except ImportError:
            pass  # Validation module not available

    return _kg_config


def _load_schema(config: KGConfig):
    """Load and validate the YAML schema."""
    from kgweave.knowledge_graph.common import load_schema

    return load_schema(config.schema_path)


def get_graph_backend(config: Optional[KGConfig] = None) -> GraphStorageBackend:
    """Return the process-wide graph backend singleton.

    Constructs the backend on first call based on configuration.
    Loads the graph from disk if the graph file exists.

    Args:
        config: Optional explicit config. If ``None``, builds from env.

    Returns:
        The active ``GraphStorageBackend`` instance.

    Raises:
        ValueError: If the configured backend is unknown.
    """
    global _graph_backend
    if _graph_backend is not None:
        return _graph_backend

    if config is None:
        config = _build_kg_config()

    backend_name = config.backend

    if backend_name == "networkx":
        from kgweave.knowledge_graph.backends import NetworkXBackend

        _graph_backend = NetworkXBackend()
    elif backend_name == "neo4j":
        from kgweave.knowledge_graph.backends import Neo4jBackend

        _graph_backend = Neo4jBackend(config=config)
    else:
        raise ValueError(
            f"Unknown KG backend: {backend_name!r}. "
            "Valid values: 'networkx', 'neo4j'."
        )

    # Load existing graph from disk if available
    graph_path = config.graph_path
    if graph_path and Path(graph_path).exists():
        try:
            _graph_backend.load(Path(graph_path))
            stats = _graph_backend.stats()
            logger.info(
                "Loaded KG from %s: %d nodes, %d edges",
                graph_path,
                stats.get("nodes", 0),
                stats.get("edges", 0),
            )
        except Exception as exc:
            logger.warning("Failed to load KG from %s: %s", graph_path, exc)

    return _graph_backend


def get_query_expander(
    backend: Optional[GraphStorageBackend] = None,
    config: Optional[KGConfig] = None,
):
    """Build a query expander from the given (or default) backend.

    Args:
        backend: Explicit backend. If ``None``, uses ``get_graph_backend()``.
        config: Explicit config for depth/term limits.

    Returns:
        A :class:`GraphQueryExpander` instance.
    """
    from kgweave.knowledge_graph.query import GraphQueryExpander

    if backend is None:
        backend = get_graph_backend()
    if config is None:
        config = _build_kg_config()

    # Phase 2: Community-aware expansion
    community_detector = None
    if config.enable_global_retrieval:
        try:
            from kgweave.knowledge_graph.community import CommunityDetector
            from kgweave.knowledge_graph.community import CommunitySummarizer

            detector = CommunityDetector(
                backend=backend,
                config=config,
                graph_path=getattr(config, "graph_path", None),
            )
            # Run detection + summarization if not already loaded from sidecar
            if not detector.is_ready:
                communities = detector.detect()
                if communities:
                    summarizer = CommunitySummarizer(config=config)
                    summaries = summarizer.summarize_all(communities, backend)
                    detector.summaries = summaries
                    detector.save_sidecar()
            community_detector = detector
        except Exception as exc:
            logger.warning("Failed to initialize community detector: %s", exc)

    return GraphQueryExpander(
        backend=backend,
        max_depth=config.max_expansion_depth,
        max_terms=config.max_expansion_terms,
        community_detector=community_detector,
        enable_global_retrieval=config.enable_global_retrieval,
        config=config,
    )


def run_post_ingestion_steps(
    backend: Optional[GraphStorageBackend] = None,
    config: Optional[KGConfig] = None,
    update_mode: bool = False,
) -> None:
    """Execute post-ingestion batch steps.

    Ordering:
        1. SV connectivity batch (if sv_filelist configured)
        2. Entity resolution (if enabled)
        3. Community detection (hierarchical Leiden)

    Args:
        backend: Populated graph backend. If None, uses singleton.
        config: KG runtime configuration. If None, builds from env.
        update_mode: Whether this is an incremental update run.
    """
    if backend is None:
        backend = get_graph_backend()
    if config is None:
        config = _build_kg_config()

    _pipeline_t0 = time.monotonic()
    logger.info("KG post-ingestion steps starting (update_mode=%s)", update_mode)

    # Step 1: SV connectivity batch
    if config.sv_filelist:
        try:
            from kgweave.knowledge_graph.extraction import (
                SVConnectivityAnalyzer,
                SV_CONNECTIVITY_SOURCE,
            )

            filelist_path = Path(config.sv_filelist)
            if not filelist_path.is_file():
                logger.warning(
                    "sv_filelist configured but file not found: %s — skipping",
                    config.sv_filelist,
                )
            else:
                if update_mode:
                    stats = backend.remove_by_source(SV_CONNECTIVITY_SOURCE)
                    logger.info("Removed previous SV connectivity: %s", stats)
                analyzer = SVConnectivityAnalyzer(
                    filelist_path=config.sv_filelist,
                    backend=backend,
                    top_module=config.sv_top_module or None,
                )
                triples = analyzer.analyze()
                if triples:
                    backend.upsert_triples(triples)
                    logger.info(
                        "SV connectivity: upserted %d connects_to triples",
                        len(triples),
                    )
        except Exception as exc:
            logger.warning("SV connectivity batch failed: %s", exc)

    # Step 2: Entity resolution
    if config.enable_entity_resolution:
        _step_t0 = time.monotonic()
        logger.info("KG step 2/3: entity resolution starting")
        try:
            from kgweave.knowledge_graph.resolution import EntityResolver

            resolver = EntityResolver(backend=backend, config=config)
            report = resolver.resolve()
            logger.info(
                "KG step 2/3: entity resolution complete — merged=%d elapsed=%.1fs",
                report.total_merged, time.monotonic() - _step_t0,
            )
        except Exception as exc:
            logger.warning("Entity resolution failed: %s", exc)

    # Step 3: Community detection (hierarchical if max_levels > 1)
    if config.enable_global_retrieval:
        _step_t0 = time.monotonic()
        logger.info("KG step 3/3: community detection starting")
        try:
            from kgweave.knowledge_graph.community import CommunityDetector
            from kgweave.knowledge_graph.community import CommunitySummarizer

            detector = CommunityDetector(
                backend=backend, config=config, graph_path=config.graph_path,
            )
            if config.community_max_levels > 1:
                hierarchy = detector.detect_hierarchical()
            else:
                detector.detect()
            if detector._detection_complete:
                summarizer = CommunitySummarizer(config=config)
                communities = detector._communities
                if communities:
                    summaries = summarizer.summarize_all(communities, backend)
                    detector.summaries = summaries
                    detector.save_sidecar()
            logger.info(
                "KG step 3/3: community detection complete — elapsed=%.1fs",
                time.monotonic() - _step_t0,
            )
        except Exception as exc:
            logger.warning("Community detection failed: %s", exc)

    logger.info(
        "KG post-ingestion steps complete — total elapsed=%.1fs",
        time.monotonic() - _pipeline_t0,
    )


def reset_singletons() -> None:
    """Reset cached singletons. Used in tests."""
    global _graph_backend, _kg_config
    _graph_backend = None
    _kg_config = None


# Re-export for convenience
from kgweave.knowledge_graph.export import export_obsidian
from kgweave.knowledge_graph.export import export_html
from kgweave.knowledge_graph.query import (
    GraphQueryExpander,
    KGTermIndex,
    clear_term_index_cache,
    get_term_index,
)
from kgweave.knowledge_graph.community import (
    CommunityDiff,
    CommunitySummary,
)

__all__ = [
    # Dispatcher functions
    "get_graph_backend",
    "get_query_expander",
    "run_post_ingestion_steps",
    "reset_singletons",
    # Re-exported types
    "GraphStorageBackend",
    "GraphQueryExpander",
    "KGConfig",
    "KGAdminClient",
    "KGIngestClient",
    "KGIngestResult",
    "KGBuilderIngestClient",
    "Entity",
    "Triple",
    "ExtractionResult",
    "EntityDescription",
    "CommunitySummary",
    "CommunityDiff",
    "KGTermIndex",
    # Utilities
    "export_obsidian",
    "export_html",
    "get_term_index",
    "clear_term_index_cache",
]
