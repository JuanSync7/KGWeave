# @summary
# Constant identifiers for the KGWeave Temporal contract: queue name,
# activity names, contract version. Keep all string literals here so a
# version bump is a single-file change reviewed by both teams.
# Exports: CONTRACT_VERSION, KG_TASK_QUEUE, KG_PHASE2B_ACTIVITY,
#          KG_DELETE_BY_SOURCE_ACTIVITY, KG_HEALTH_ACTIVITY
# Deps: (none)
# @end-summary
"""Constants for the KGWeave wire contract."""

CONTRACT_VERSION = "v1"
"""Version pin shared by both repos. Bump on any schema-breaking change."""

KG_TASK_QUEUE = "kgweave-default"
"""Temporal task queue polled by KGWeave's worker fleet."""

KG_PHASE2B_ACTIVITY = "kg_phase2b"
"""Activity name for full-document KG ingest from CleanDocumentStore."""

KG_DELETE_BY_SOURCE_ACTIVITY = "kg_delete_by_source"
"""Activity name for source-key-targeted deletion (used by GC + migration)."""

KG_HEALTH_ACTIVITY = "kg_health"
"""Activity name for backend stats / health probe."""
