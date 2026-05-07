# @summary
# kgweave.client — thin facade returning a KGQueryService implementation
# chosen by env: in-process by default, HTTPKGQueryService when
# KGWEAVE_API_URL is set. Lets RagWeave (or any other consumer) flip
# between transports without import surgery.
# Exports: get_client, HTTPKGQueryService
# @end-summary
"""Transport-agnostic client facade for the KGWeave read-side API."""

from kgweave.client.factory import get_client
from kgweave.client.http_client import HTTPKGQueryService
from kgweave.service.query_service import KGQueryService

__all__ = ["get_client", "HTTPKGQueryService", "KGQueryService"]
