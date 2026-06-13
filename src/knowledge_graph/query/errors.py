"""Structured Cypher execution errors for the raw-Cypher path.

The runner's :func:`_run_raw` path executes arbitrary read-only Cypher
against Kuzu. When Kuzu rejects a query it raises a ``RuntimeError`` whose
message text is engine-specific and unhelpful to leak verbatim. This module
translates those exceptions into a typed :class:`CypherError` carrying a
classified ``kind`` plus an optional ``difflib`` near-miss ``suggestion``
drawn from the package's *live* vocabulary (node label ``Node``, the
rel-table set, and the canonical ``:Node`` property set).

Classification ported and adapted from the research prototype's
``_cypher_validate.py`` (``research/ast_experiment/src/semantic/queries/``).
The package differences:

* node labels are ``{"Node"}`` (not ``{"N"}``);
* rel-tables are the UPPERCASE names in
  :data:`knowledge_graph.query.intents.ALL_EDGE_TYPES`;
* properties are the canonical ``:Node`` columns
  (:data:`knowledge_graph.query.compiler.NODE_RETURN_FIELDS`).

A zero-match query is NOT an error — it returns an empty, successful
``QueryResult``. Only an exception raised by ``conn.execute`` becomes a
``CypherError``.

KIND TAXONOMY:
    syntax           — parser/connection exception in the query text
    unknown_label    — referenced node label does not exist
    unknown_edge     — referenced relationship (rel-table) does not exist
    unknown_property — referenced property does not exist on ``Node``
    engine           — anything else Kuzu raises (wrapped; never leaked raw)
"""

from __future__ import annotations

import difflib
from typing import Any

from knowledge_graph.query.compiler import NODE_RETURN_FIELDS
from knowledge_graph.query.intents import ALL_EDGE_TYPES

__all__ = ["CypherError", "classify_cypher_error"]


_VALID_KINDS = frozenset(
    ("syntax", "unknown_label", "unknown_edge", "unknown_property", "engine")
)

_VALID_NODE_LABELS: frozenset[str] = frozenset({"Node"})
_VALID_PROPERTIES: frozenset[str] = frozenset(NODE_RETURN_FIELDS)
_VALID_EDGES: frozenset[str] = frozenset(ALL_EDGE_TYPES)


class CypherError(Exception):
    """Structured error raised on the raw-Cypher path instead of a raw
    Kuzu ``RuntimeError``.

    Attributes:
        kind:       one of ``syntax | unknown_label | unknown_edge |
                    unknown_property | engine``.
        message:    human-readable description (never a raw traceback).
        suggestion: nearest-match name from the live vocabulary, or
                    ``None`` when no close match exists.
    """

    def __init__(
        self, kind: str, message: str, suggestion: str | None = None
    ) -> None:
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"CypherError.kind must be one of {sorted(_VALID_KINDS)}, "
                f"got {kind!r}"
            )
        self.kind = kind
        self.message = message
        self.suggestion = suggestion
        tail = f" (did you mean {suggestion!r}?)" if suggestion else ""
        super().__init__(f"[{kind}] {message}{tail}")

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict view (handy for JSON payloads)."""
        return {
            "kind": self.kind,
            "message": self.message,
            "suggestion": self.suggestion,
        }


# --------------------------------------------------------------- helpers


def _suggest(bad: str, candidates: frozenset[str]) -> str | None:
    if not bad or not candidates:
        return None
    matches = difflib.get_close_matches(bad, sorted(candidates), n=1, cutoff=0.4)
    return matches[0] if matches else None


def _extract_after(msg: str, needle: str) -> str | None:
    """Return the identifier token following ``needle`` in ``msg``.

    Plain string scan (no regex): the token ends at the first whitespace,
    period, quote, or closing paren.
    """
    idx = msg.find(needle)
    if idx == -1:
        return None
    after = msg[idx + len(needle):]
    name = ""
    for ch in after:
        if ch in (" ", "\t", "\n", ".", "'", '"', ")"):
            break
        name += ch
    return name.strip() or None


# --------------------------------------------------------------- classify


def classify_cypher_error(exc: Exception) -> CypherError:
    """Translate a raw Kuzu exception into a structured :class:`CypherError`.

    Inspects the message with plain substring checks against the live
    package vocabulary. Never re-raises the raw exception; the catch-all
    is ``kind="engine"``.
    """
    msg = str(exc)

    # 1. Syntax / parser / connection errors.
    if (
        "Parser exception" in msg
        or "parser exception" in msg
        or "Connection exception" in msg
        or "Syntax error" in msg
        or "SyntaxError" in msg
        or "Cannot parse" in msg
    ):
        return CypherError(kind="syntax", message=msg, suggestion=None)

    # 2. Binder exceptions — unknown property, or unknown table (label/edge).
    if "Binder exception" in msg or "binder exception" in msg:
        # 2a. Unknown property: "Cannot find property X for n."
        if (
            "Cannot find property" in msg
            or "is not a property" in msg
        ):
            prop = _extract_after(msg, "Cannot find property ")
            return CypherError(
                kind="unknown_property",
                message=msg,
                suggestion=_suggest(prop, _VALID_PROPERTIES) if prop else None,
            )

        # 2b. Unknown table: "Table X does not exist."
        if "does not exist" in msg:
            bad = _extract_after(msg, "Table ")
            if bad:
                if bad in _VALID_EDGES:
                    # Defensive: a valid edge shouldn't reach here.
                    return CypherError(kind="engine", message=msg)
                if bad in _VALID_NODE_LABELS:
                    return CypherError(kind="engine", message=msg)
                # Rel-tables are UPPERCASE; node label is "Node". An
                # all-uppercase / underscore identifier is edge-like.
                if _looks_like_edge(bad):
                    return CypherError(
                        kind="unknown_edge",
                        message=msg,
                        suggestion=_suggest(bad, _VALID_EDGES),
                    )
                return CypherError(
                    kind="unknown_label",
                    message=msg,
                    suggestion=_suggest(bad, _VALID_NODE_LABELS),
                )
            return CypherError(kind="unknown_label", message=msg)

        return CypherError(kind="engine", message=msg)

    # 3. "does not exist" without an explicit Binder marker.
    if "does not exist" in msg:
        bad = _extract_after(msg, "Table ")
        if bad:
            if _looks_like_edge(bad):
                return CypherError(
                    kind="unknown_edge",
                    message=msg,
                    suggestion=_suggest(bad, _VALID_EDGES),
                )
            return CypherError(
                kind="unknown_label",
                message=msg,
                suggestion=_suggest(bad, _VALID_NODE_LABELS),
            )
        return CypherError(kind="engine", message=msg)

    # 4. Catch-all.
    return CypherError(kind="engine", message=msg)


def _looks_like_edge(name: str) -> bool:
    """Heuristic: rel-tables are UPPERCASE / underscore-joined; the node
    label is ``Node`` (mixed case). Treat an all-uppercase or
    underscore-bearing identifier as edge-like."""
    if not name:
        return False
    if "_" in name:
        return True
    if name.isupper():
        return True
    return False
