# @summary
# KGWeave package — knowledge graph subsystem and Temporal worker.
# Subpackages: client (queries), admin (lifecycle), contracts (Pydantic +
# Temporal handles), service, worker, knowledge_graph, core (legacy).
# Top-level re-exports: set_default_llm_factory — host-app dependency
# injection hook so RagWeave (or any host) can register its LLM provider
# without importing internal kgweave modules.
# @end-summary
"""KGWeave: knowledge graph subsystem and Temporal worker."""

from kgweave.knowledge_graph.common.protocols import set_default_llm_factory

__all__ = ["set_default_llm_factory"]
