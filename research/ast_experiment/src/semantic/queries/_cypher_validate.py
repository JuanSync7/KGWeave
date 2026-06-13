"""Cypher error classification and CypherError definition.

This module translates kuzu RuntimeErrors into structured, helpful
``CypherError`` exceptions — never exposing raw kuzu tracebacks to callers.

DESIGN — why raise, not return:
    ``cypher_query`` always returns ``CypherResult`` on success (zero matches
    is still success: empty rows, populated columns).  On failure it raises
    ``CypherError``.  This keeps the return type clean (no union) and matches
    how ``evals/cypher_ab/run_ab.py`` treats errors (catch + grade as a miss).

CLASSIFICATION — kuzu exception message inspection only:
    We inspect the exception message with plain ``in`` substring checks (NO regex).
    Simple string operations (split on quotes/spaces) extract the offending
    identifier.  difflib.get_close_matches provides near-miss suggestions.

    VERSION PIN: the substrings below ("Binder exception", "Cannot find
    property", "Table ... does not exist", "Connection exception: Query is
    empty", etc.) are matched against kuzu's message text as emitted by
    **kuzu>=0.11** (the pinned core dep). They are inherently version-brittle;
    if a kuzu bump changes the wording, classification degrades gracefully to
    kind="engine" (the catch-all never swallows an error) rather than
    mis-routing — but the kind taxonomy below would need re-pinning. When
    bumping kuzu, re-run tests/queries/test_cypher_fail_loud.py first.

KIND TAXONOMY:
    syntax           — kuzu parser exception / syntax error in the query text
    unknown_label    — referenced node label does not exist (only "N" is valid)
    unknown_edge     — referenced relationship type does not exist
    unknown_property — referenced property does not exist on table N
    engine           — anything else kuzu raises (wrapped; never leaked raw)

LIVE VOCABULARY (derived from the graph at call time — never hardcoded):
    node labels   = {"N"}
    edge types    = from _EDGE_TYPES(graph)
    properties    = {"id", "role", "name", "path", "direction"}

NO ``import re`` / ``from re`` in this module.
"""

from __future__ import annotations

import difflib
from typing import Any

# ---------------------------------------------------------------------------
# CypherError — the only exception type callers of cypher_query ever see
# ---------------------------------------------------------------------------

_VALID_KINDS = frozenset(
    ("syntax", "unknown_label", "unknown_edge", "unknown_property", "engine")
)

_VALID_NODE_LABELS = {"N"}
_VALID_PROPERTIES = {"id", "role", "name", "path", "direction"}


class CypherError(Exception):
    """Structured Cypher execution error raised by ``cypher_query``.

    Attributes:
        kind:       One of ``syntax | unknown_label | unknown_edge |
                    unknown_property | engine``.
        message:    Human-readable description of the problem (never a raw
                    Python traceback).
        suggestion: Nearest-match name from the live vocabulary, or ``None``
                    when no close match exists.

    Usage::

        try:
            result = cypher_query(graph, q)
        except CypherError as e:
            print(e.kind, e.message, e.suggestion)
            print(e.to_dict())   # typed payload as dict
    """

    def __init__(self, kind: str, message: str, suggestion: str | None = None) -> None:
        if kind not in _VALID_KINDS:
            raise ValueError(f"CypherError.kind must be one of {_VALID_KINDS}, got {kind!r}")
        self.kind = kind
        self.message = message
        self.suggestion = suggestion
        super().__init__(f"[{kind}] {message}" + (f" (did you mean {suggestion!r}?)" if suggestion else ""))

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation of this error.

        Convenient for callers that need a typed payload without depending on
        the exception class directly (e.g. JSON serialisation).
        """
        return {
            "kind": self.kind,
            "message": self.message,
            "suggestion": self.suggestion,
        }


# ---------------------------------------------------------------------------
# _extract_quoted — pull the first single- or double-quoted token from a string
# ---------------------------------------------------------------------------

def _extract_quoted(text: str) -> str | None:
    """Extract the first single- or double-quoted identifier from *text*.

    Uses only plain string operations (no regex).  Returns ``None`` if no
    quoted token is found.
    """
    for quote in ('"', "'"):
        if quote in text:
            parts = text.split(quote)
            # parts[0] is before first quote, parts[1] is between first pair
            if len(parts) >= 3:
                candidate = parts[1].strip()
                if candidate:
                    return candidate
    return None


# ---------------------------------------------------------------------------
# classify_kuzu_error — the robust core of S2
# ---------------------------------------------------------------------------

def classify_kuzu_error(
    exc: Exception,
    graph: dict[str, Any],
) -> "CypherError":
    """Translate a kuzu exception into a structured ``CypherError``.

    Inspects the exception message with plain substring checks (NO regex).
    Extracts the offending identifier via simple string splits and computes
    a near-miss suggestion from the live vocabulary using ``difflib``.

    Args:
        exc:   The raw exception raised by ``conn.execute()``.
        graph: The KG dict — used to derive the live edge-type vocabulary.

    Returns:
        A ``CypherError`` ready to be re-raised.
    """
    from ._kuzu_load import _EDGE_TYPES  # local import to keep kuzu lazy

    msg = str(exc)
    # Normalise — remove traceback preamble if kuzu included one.  We only
    # want the semantic error message, not the Python call stack.  We use
    # split/join on plain text markers (no regex).
    clean_msg = _strip_traceback(msg)

    # -----------------------------------------------------------------------
    # 1. Syntax / parser errors — includes kuzu "Connection exception: Query is empty"
    # -----------------------------------------------------------------------
    if (
        "Parser exception" in msg
        or "parser exception" in msg
        or "Connection exception" in msg
        or "SyntaxError" in msg
        or "Syntax error" in msg
        or "Cannot parse" in msg
    ):
        return CypherError(kind="syntax", message=clean_msg, suggestion=None)

    # -----------------------------------------------------------------------
    # 2. Binder exceptions — unknown table (label or edge) or unknown property
    # -----------------------------------------------------------------------
    if "Binder exception" in msg or "binder exception" in msg:
        # Extract the quoted identifier from the binder message
        bad_id = _extract_quoted(clean_msg)

        # 2a. Unknown property — kuzu: "Cannot find property X for n."
        #     Also covers "is not a property of" (older kuzu versions)
        if (
            "Cannot find property" in msg
            or "is not a property" in msg
            or ("property" in msg.lower() and "not found" in msg.lower())
        ):
            # Extract the property name from "Cannot find property X for n."
            prop_name = _extract_property_name(msg) or bad_id
            suggestion = None
            if prop_name:
                suggestion = _suggest(prop_name, list(_VALID_PROPERTIES))
            return CypherError(
                kind="unknown_property",
                message=clean_msg,
                suggestion=suggestion,
            )

        # 2b. "Table <X> does not exist"
        if "does not exist" in msg or "not exist" in msg:
            bad_name = _extract_table_name(msg) or bad_id
            # Distinguish unknown_label vs unknown_edge by checking the live vocab
            live_edges = sorted(_EDGE_TYPES(graph))
            if bad_name:
                # If bad_name matches (case-insensitively) something close to an edge type
                # OR it's clearly a node label (contains uppercase, looks like a label),
                # we classify accordingly.
                edge_suggestion = _suggest(bad_name, live_edges)
                label_suggestion = _suggest(bad_name, list(_VALID_NODE_LABELS))
                # Heuristic: if close to an edge type → unknown_edge
                # If close to a node label or nothing → unknown_label
                # We check whether the "Table does not exist" appears in a context that
                # suggests an edge table (REL) vs node table (NODE).
                # kuzu's message for edge: "Table <X> does not exist."
                # We also check: is bad_name already a known node label? No → unknown_label.
                if bad_name in _VALID_NODE_LABELS:
                    # It IS valid — this shouldn't happen, but defend
                    return CypherError(kind="engine", message=clean_msg, suggestion=None)
                # Check if it looks more like an edge (no uppercase, snake_case)
                if _looks_like_edge(bad_name) and edge_suggestion:
                    return CypherError(
                        kind="unknown_edge",
                        message=clean_msg,
                        suggestion=edge_suggestion,
                    )
                # Otherwise treat as unknown_label
                return CypherError(
                    kind="unknown_label",
                    message=clean_msg,
                    suggestion=label_suggestion,
                )
            # Fallback
            return CypherError(kind="unknown_label", message=clean_msg, suggestion=None)

        # 2c. Generic binder — try property first, then label
        if bad_id:
            if bad_id.lower() in {p.lower() for p in _VALID_PROPERTIES}:
                # It IS a valid property — the error is something else
                pass
            elif bad_id in _VALID_NODE_LABELS:
                pass
            else:
                # Could be unknown property
                prop_suggestion = _suggest(bad_id, list(_VALID_PROPERTIES))
                if prop_suggestion:
                    return CypherError(
                        kind="unknown_property",
                        message=clean_msg,
                        suggestion=prop_suggestion,
                    )
        return CypherError(kind="engine", message=clean_msg, suggestion=None)

    # -----------------------------------------------------------------------
    # 3. Runtime errors that mention "does not exist" without "Binder exception"
    # -----------------------------------------------------------------------
    if "does not exist" in msg:
        bad_name = _extract_table_name(msg)
        live_edges = sorted(_EDGE_TYPES(graph))
        if bad_name:
            if _looks_like_edge(bad_name):
                suggestion = _suggest(bad_name, live_edges)
                return CypherError(
                    kind="unknown_edge",
                    message=clean_msg,
                    suggestion=suggestion,
                )
            else:
                suggestion = _suggest(bad_name, list(_VALID_NODE_LABELS))
                return CypherError(
                    kind="unknown_label",
                    message=clean_msg,
                    suggestion=suggestion,
                )
        return CypherError(kind="engine", message=clean_msg, suggestion=None)

    # -----------------------------------------------------------------------
    # 4. Catch-all — wrap as engine error
    # -----------------------------------------------------------------------
    return CypherError(kind="engine", message=clean_msg, suggestion=None)


# ---------------------------------------------------------------------------
# Helpers — all use plain string operations (no regex)
# ---------------------------------------------------------------------------

def _extract_property_name(msg: str) -> str | None:
    """Extract the property name from 'Cannot find property X for n.' messages.

    Uses only plain string split (no regex).  For example:
        'Binder exception: Cannot find property foobar for n.'
    returns 'foobar'.
    """
    needle = "Cannot find property "
    idx = msg.find(needle)
    if idx == -1:
        return None
    after = msg[idx + len(needle):]
    # Property name ends at whitespace or end of string
    name = ""
    for ch in after:
        if ch in (" ", "\t", "\n", ".", "'", '"', ")"):
            break
        name += ch
    return name.strip() or None


def _strip_traceback(msg: str) -> str:
    """Remove a Python traceback preamble from *msg* if present.

    Uses plain split on the 'Traceback' line — no regex.  Returns just the
    last meaningful error line(s) if a traceback is found.
    """
    marker = "Traceback (most recent call last)"
    if marker not in msg:
        return msg.strip()
    # Keep only the part after the last blank traceback paragraph
    # Heuristic: the actual error description is in the last non-empty line(s)
    lines = msg.splitlines()
    # Find lines that are NOT traceback boilerplate (not indented, not "File ...", not "  ...")
    error_lines = []
    in_traceback = False
    for line in lines:
        if marker in line:
            in_traceback = True
            continue
        if in_traceback:
            if line.startswith("  ") or line.startswith("\t"):
                continue  # indented frame — skip
            if line.startswith("File "):
                continue
            # Non-indented line after a traceback is the actual error class/message
            error_lines.append(line)
        else:
            error_lines.append(line)
    clean = "\n".join(l for l in error_lines if l.strip())
    return clean.strip() if clean.strip() else msg.strip()


def _extract_table_name(msg: str) -> str | None:
    """Extract the table name from 'Table <X> does not exist' messages.

    Uses only plain string split (no regex).
    """
    needle = "Table "
    lower = msg
    idx = lower.find(needle)
    if idx == -1:
        needle = "table "
        idx = lower.find(needle)
    if idx == -1:
        return None
    after = msg[idx + len(needle):]
    # Table name ends at whitespace, period, quote, or end of token
    name = ""
    for ch in after:
        if ch in (" ", "\t", "\n", ".", "'", '"', ")"):
            break
        name += ch
    return name.strip() or None


def _looks_like_edge(name: str) -> bool:
    """Heuristic: does *name* look like a snake_case edge type rather than a PascalCase label?

    Edge types in this graph are snake_case (reads, has_class, of_type, …).
    Node labels are uppercase or PascalCase (N, Node, Module, …).
    Uses only str methods — no regex.
    """
    if not name:
        return False
    # If it's all lowercase or contains underscores → edge-like
    if "_" in name or name == name.lower():
        return True
    # If it starts with uppercase → label-like
    if name[0].isupper():
        return False
    return True


def _suggest(bad: str, candidates: list[str]) -> str | None:
    """Return the closest candidate to *bad* from *candidates*, or None.

    Uses ``difflib.get_close_matches`` with cutoff=0.4 so moderate typos
    still get a suggestion.  Returns a single string or None.
    """
    if not candidates or not bad:
        return None
    matches = difflib.get_close_matches(bad, candidates, n=1, cutoff=0.4)
    return matches[0] if matches else None
