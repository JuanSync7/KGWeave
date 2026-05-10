"""Common contracts, configuration types, and shared helpers for the KG subsystem."""

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from kgweave.knowledge_graph.common.schemas import (
    Entity,
    EntityDescription,
    ExtractionResult,
    LayerDiff,
    Triple,
)
from kgweave.knowledge_graph.common.protocols import (
    LLMClient,
    clear_default_llm_factory,
    get_default_llm,
    set_default_llm_factory,
)
from kgweave.knowledge_graph.common.types import (
    KGConfig,
    ProjectConventions,
    SchemaDefinition,
    load_schema,
)
from kgweave.knowledge_graph.common.utils import derive_gliner_labels
from kgweave.knowledge_graph.common.validation import (
    KGConfigValidationError,
    PatternWarning,
    validate_edge_types,
    validate_path_patterns,
)
