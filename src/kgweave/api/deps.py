# @summary
# Shared FastAPI dependencies for the KGWeave HTTP API: service injection
# and edge-level bearer-token auth. The service dependency is overridable
# via app.dependency_overrides so tests can inject fakes.
# Exports: get_service, set_service, require_auth
# Deps: fastapi, kgweave.service.query_service
# @end-summary
"""Dependency-injection helpers for the KGWeave HTTP API."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from kgweave.service.query_service import (
    KGQueryService,
    build_default_query_service,
)

_service: Optional[KGQueryService] = None


def set_service(service: KGQueryService) -> None:
    """Install the process-wide query service (used at startup and in tests)."""
    global _service
    _service = service


def get_service() -> KGQueryService:
    """Return the active query service, building a default if unset."""
    global _service
    if _service is None:
        _service = build_default_query_service()
    return _service


def require_auth(
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Bearer-token gate. No-op when ``KGWEAVE_API_TOKEN`` is unset.

    Treat the whole API as one trust boundary — there is no per-route
    authorization logic.
    """
    expected = os.environ.get("KGWEAVE_API_TOKEN")
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid bearer token",
        )


# Re-exported for route modules' Depends(...) signatures.
ServiceDep = Depends(get_service)
AuthDep = Depends(require_auth)
