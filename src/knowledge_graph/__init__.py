"""KGWeave public facade — Phase A stub.

This module re-exports the minimum surface needed for Phase A (the
``KGStore``). The full builder + query facade is added in Phase F per
``docs/plans/KUZU_PORT_PLAN.md``.
"""

from __future__ import annotations

from knowledge_graph.store import KGStore

__version__ = "0.1.0a1"
__all__ = ["KGStore", "__version__"]
