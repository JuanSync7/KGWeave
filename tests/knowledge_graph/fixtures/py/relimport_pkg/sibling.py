"""Sibling module for v1.10-#2 relative-import resolution fixture.

Defines top-level ``foo`` so the package-sibling consumer can do
``from .sibling import foo`` and capture it inside a lambda. The
connector should resolve the relative import against the consuming
module's package path and tag the capture as ``cross-file-import``
with ``origin_module == "sibling"`` (the corpus assigns PyModule.name
from the file stem).
"""

from __future__ import annotations


def foo(x):
    return x
