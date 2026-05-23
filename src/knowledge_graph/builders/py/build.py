"""Multi-file Python build entry point.

Thin wrapper around :func:`knowledge_graph.builders.py.walker.lift_python`
that mirrors the surface of :func:`builders.sv.build.build_kg` so a
caller can introspect the in-memory graph without going through the
Kuzu writer. v1 has no cross-file semantic pass — each file is lifted
independently and the resulting node lists are returned keyed by path.

Cross-file resolution (``from x import y`` -> Origin of ``x``) happens
in the Python ↔ MD connector at run-connectors time, not here.
"""

from __future__ import annotations

from pathlib import Path

from .walker import PyNode, lift_python


def build_kg(py_paths: list[Path]) -> dict[str, list[PyNode]]:
    """Lift each path's content to a PyNode list, keyed by path string.

    Returns a ``{path_str: [PyNode, ...]}`` map. Caller is responsible
    for stable ordering of paths if downstream consumers care about
    iteration order.
    """
    out: dict[str, list[PyNode]] = {}
    for p in py_paths:
        path = Path(p)
        out[str(path)] = lift_python(path.read_bytes())
    return out


__all__ = ["build_kg"]
