# @summary
# kgweave.admin — intentional entry point for admin/lifecycle code that
# needs deep backend access (CLI tools, GC, validation, migrations).
#
# This namespace exists to make the architectural distinction explicit:
#
#   - Retrieval-path code uses kgweave.client (in-process or HTTP).
#   - Ingest-path code uses the Temporal worker on kgweave-default.
#   - Admin/lifecycle code uses kgweave.admin (deep backend access).
#
# The functions here return the raw GraphStorageBackend; callers can
# invoke any backend method including mutations. This is INTENTIONALLY
# more powerful than KGQueryService — it is for tools that co-deploy
# with KGWeave (CLI, jobs), not for cross-service consumers.
# Exports: get_admin_backend, GraphStorageBackend
# @end-summary
"""Admin/lifecycle entry point — deep backend access for CLI + GC tools."""

from kgweave.admin.facade import get_admin_backend
from kgweave.knowledge_graph.backend import GraphStorageBackend

__all__ = ["get_admin_backend", "GraphStorageBackend"]
