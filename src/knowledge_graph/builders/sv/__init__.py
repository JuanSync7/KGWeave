"""SV builder package — lift/unlift/promote and build_kg facade.

Re-exports the stable surface used by Phase C (the Kuzu writer) and by
external callers.
"""

from __future__ import annotations

from .build import build_kg
from .lift import lift
from .semantic import promote
from .unlift import emit, unlift
from .writer import ExtractStats, WriteStats, build_and_store, extract, write_graph

__all__ = [
    "build_kg",
    "lift",
    "unlift",
    "emit",
    "promote",
    "write_graph",
    "build_and_store",
    "extract",
    "WriteStats",
    "ExtractStats",
]
