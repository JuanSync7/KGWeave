"""MD builder package — minimal markdown lift + facade-shaped extract.

Mirrors the SV builder's public surface (``extract`` returns a 3-tuple
whose last element is :class:`ExtractStats`) so the facade dispatch
treats both builders uniformly. The lift surface is intentionally
narrow: documents, ATX/setext headings, fenced code blocks, and
inline-code spans. Links, images, tables, lists, emphasis — anything
not load-bearing for cross-builder connectors — is *not* lifted.

The byte-precise spans come from a hand-rolled scanner (see
:mod:`knowledge_graph.builders.md.lift`) rather than from mistune's
tokens, because mistune tokens carry no source offsets. The scanner is
deterministic and idempotent (invariant I6).
"""

from __future__ import annotations

from .lift import MdNode, lift_markdown
from .writer import extract, write_md_graph

__all__ = ["lift_markdown", "MdNode", "write_md_graph", "extract"]
