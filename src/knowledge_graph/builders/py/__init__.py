"""Python builder package — libcst-driven lift + Kuzu writer.

Mirrors the surface of :mod:`knowledge_graph.builders.sv` and
:mod:`knowledge_graph.builders.md`:

* :func:`lift_python` — parse Python source bytes into a flat list of
  :class:`PyNode` objects (module / function / class / import).
* :func:`write_py_graph` — write one file's PyNodes to a Kuzu store.
* :func:`extract` — incremental extract with replacement-merge.

v1 scope: module, def, class, top-level import (incl. ``from x import y``).
Deferred to a later slate (see JOURNAL): decorators, async def, type
aliases (PEP 695), walrus, match-case, comprehension scopes, lambda
capture, properties, descriptors, metaclasses, conditional imports,
``__all__`` re-export, ``if TYPE_CHECKING:`` blocks, type stub files.
"""

from __future__ import annotations

from .walker import PyNode, lift_python
from .writer import extract, write_py_graph

__all__ = ["lift_python", "PyNode", "write_py_graph", "extract"]
