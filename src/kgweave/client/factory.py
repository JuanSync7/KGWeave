# @summary
# Factory: returns an HTTP-backed KGQueryService when KGWEAVE_API_URL is
# set in the environment, otherwise the default in-process implementation.
# Cached as a process-wide singleton.
# Exports: get_client, reset_client
# @end-summary
"""Pick the right KGQueryService implementation for this process."""

from __future__ import annotations

import os
from typing import Optional

from kgweave.service.query_service import (
    KGQueryService,
    build_default_query_service,
)

_client: Optional[KGQueryService] = None


def get_client() -> KGQueryService:
    """Return the process-wide KG query client.

    When ``KGWEAVE_API_URL`` is set, returns an :class:`HTTPKGQueryService`
    that calls the remote KGWeave API. Otherwise returns the in-process
    :class:`DefaultKGQueryService`.
    """
    global _client
    if _client is not None:
        return _client

    base_url = os.environ.get("KGWEAVE_API_URL", "").strip()
    if base_url:
        from kgweave.client.http_client import HTTPKGQueryService  # noqa: PLC0415

        token = os.environ.get("KGWEAVE_API_TOKEN", "").strip() or None
        timeout = float(os.environ.get("KGWEAVE_API_TIMEOUT", "5.0"))
        _client = HTTPKGQueryService(
            base_url=base_url, token=token, timeout=timeout,
        )
    else:
        _client = build_default_query_service()
    return _client


def reset_client() -> None:
    """Drop the cached client (used in tests)."""
    global _client
    _client = None
