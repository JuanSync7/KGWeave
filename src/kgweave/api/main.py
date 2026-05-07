# @summary
# Uvicorn entry point: ``uvicorn kgweave.api.main:app`` boots the default
# in-process query service. For programmatic use call ``create_app()`` and
# pass an explicit service.
# Exports: app
# @end-summary
"""Module-level ASGI app for `uvicorn kgweave.api.main:app`."""

from __future__ import annotations

from kgweave.api.app import create_app

app = create_app()
