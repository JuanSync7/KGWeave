# @summary
# Route registry — assembles the v1 APIRouter from per-resource modules.
# Exports: v1_router
# @end-summary
"""KGWeave API route assembly."""

from fastapi import APIRouter

from kgweave.api.routes import entities, expand, health, paths, term_index

v1_router = APIRouter()
v1_router.include_router(health.router)
v1_router.include_router(expand.router)
v1_router.include_router(term_index.router)
v1_router.include_router(entities.router)
v1_router.include_router(paths.router)

__all__ = ["v1_router"]
