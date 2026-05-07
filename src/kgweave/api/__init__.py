# @summary
# KGWeave HTTP API package (Step C). Exposes a FastAPI app that serves the
# read-side KG surface — expansion, term-index lookup, entity probe, paths.
# Public API: create_app(service=None) factory and a module-level ``app``
# constructed from defaults for `uvicorn kgweave.api.main:app`.
# Subpackages: routes
# Exports: create_app
# @end-summary
"""KGWeave HTTP service package."""

from kgweave.api.app import create_app

__all__ = ["create_app"]
