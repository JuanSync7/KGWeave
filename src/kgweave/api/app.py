# @summary
# FastAPI app factory. Wires the v1 router, registers a uniform error
# handler that returns ErrorResponse envelopes, and exposes the OpenAPI
# schema generated from kgweave.contracts.http models.
# Exports: create_app
# Deps: fastapi, kgweave.api.routes, kgweave.contracts
# @end-summary
"""KGWeave HTTP API application factory."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kgweave.api.deps import set_service
from kgweave.api.routes import v1_router
from kgweave.contracts import CONTRACT_VERSION, ErrorResponse
from kgweave.service.query_service import EntityNotFound, KGQueryService


def create_app(service: Optional[KGQueryService] = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        service: Optional pre-built query service. When supplied it becomes
            the default returned by ``get_service``; otherwise the default
            in-process service is constructed lazily on first request.
    """
    app = FastAPI(
        title="KGWeave API",
        version=CONTRACT_VERSION,
        description=(
            "Read-side knowledge-graph queries: expansion, term-index "
            "lookup, entity probe, and path-pattern evaluation."
        ),
    )

    if service is not None:
        set_service(service)

    app.include_router(v1_router, prefix="/v1")

    @app.exception_handler(EntityNotFound)
    async def _entity_not_found(_: Request, exc: EntityNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error="entity_not_found", detail=str(exc)
            ).model_dump(),
        )

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="invalid_request", detail=str(exc)
            ).model_dump(),
        )

    return app
