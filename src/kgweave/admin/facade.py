# @summary
# Admin-side facade: returns the configured graph backend with full
# read+write capability. Delegates to the same singleton resolver used
# by kgweave.knowledge_graph so admin and ingest agree on backend state.
# Exports: get_admin_backend
# @end-summary
"""Admin facade for CLI/lifecycle tools that need deep backend access."""

from __future__ import annotations

from typing import Optional

from kgweave.knowledge_graph.backend import GraphStorageBackend


def get_admin_backend() -> GraphStorageBackend:
    """Return the active graph backend with read+write capability.

    Use this from CLI tools, GC engines, validation utilities, or any
    co-deployed admin code that needs to call low-level backend methods
    (``get_all_entities``, ``remove_by_source``, etc.) and mutations.

    For retrieval-path or cross-service consumers, prefer
    ``kgweave.client.get_client()`` which routes through the
    high-level ``KGQueryService`` interface and respects the
    in-process / HTTP transport switch.
    """
    from kgweave.knowledge_graph import get_graph_backend  # noqa: PLC0415

    return get_graph_backend()


def try_get_admin_backend() -> Optional[GraphStorageBackend]:
    """Return the backend or ``None`` when it cannot be initialised.

    Mirrors the defensive ``try/except`` pattern that CLI tools use when
    they want to continue running with the KG check skipped (e.g. if the
    backend is offline during a partial outage).
    """
    try:
        return get_admin_backend()
    except Exception:
        return None
