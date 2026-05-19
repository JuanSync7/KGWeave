"""Connector protocol — pluggable derived-edge synthesizers.

A connector reads an existing graph and writes new edges (or nodes) based
on cross-builder synthesis rules (e.g. linking SV module-instance names
to Bazel build targets). v1 ships no non-trivial connectors; this file
defines the stable protocol so consumers can plug their own in.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Connector"]


@runtime_checkable
class Connector(Protocol):
    """Pluggable graph-synthesis hook.

    Implementations are plain Python objects (or modules) carrying the
    three attributes below.

    * ``name``     — unique registry key.
    * ``requires`` — list of ``source`` strings this connector reads from.
                     The runner refuses to run a connector whose required
                     sources are not present in the store.
    * ``synthesize(store)`` — perform the write; return the number of
                              edges (or rows) emitted.
    """

    name: str
    requires: list[str]

    def synthesize(self, store) -> int: ...
