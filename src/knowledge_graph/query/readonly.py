"""Read-only enforcement for ``RawCypher`` intents (I8).

The check operates **only on the Cypher text** — bound parameter values
are passed to Kuzu out-of-band and cannot smuggle DDL/DML in. Even so we
strip string literals and comments before scanning so that a literal
``WHERE n.name = 'CREATE'`` does not trip the regex.

Banned keyword set: ``CREATE``, ``MERGE``, ``DELETE``, ``SET``,
``REMOVE``, ``DROP``, ``ALTER``, ``COPY``, ``CALL``. ``CALL`` is
rejected by default — Kuzu's writable procedures are namespaced under
``CALL``. If a read-only ``CALL`` procedure is later needed, gate it
through a dedicated intent rather than carving an exception here.
"""

from __future__ import annotations

import re

__all__ = ["assert_read_only", "ReadOnlyViolation", "BANNED_KEYWORDS"]


class ReadOnlyViolation(ValueError):
    """Raised when a ``RawCypher`` body contains a banned write keyword."""


BANNED_KEYWORDS: tuple[str, ...] = (
    "CREATE",
    "MERGE",
    "DELETE",
    "SET",
    "REMOVE",
    "DROP",
    "ALTER",
    "COPY",
    "CALL",
)


# Match ``\b(KW1|KW2|...)\b`` case-insensitively. We upper-case the
# scrubbed cypher before matching, so the pattern is upper-only.
_BANNED_RE = re.compile(r"\b(" + "|".join(BANNED_KEYWORDS) + r")\b")

# Strip ``//`` line comments and ``/* ... */`` block comments.
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# Strip single- and double-quoted string literals (with backslash-escapes).
_SINGLE_STR_RE = re.compile(r"'(?:\\.|[^'\\])*'")
_DOUBLE_STR_RE = re.compile(r'"(?:\\.|[^"\\])*"')


def _scrub(cypher: str) -> str:
    """Return ``cypher`` with comments and string literals replaced by spaces."""
    out = _BLOCK_COMMENT_RE.sub(" ", cypher)
    out = _LINE_COMMENT_RE.sub(" ", out)
    out = _SINGLE_STR_RE.sub(" ", out)
    out = _DOUBLE_STR_RE.sub(" ", out)
    return out.upper()


def assert_read_only(cypher: str) -> None:
    """Raise :class:`ReadOnlyViolation` if ``cypher`` contains a write keyword.

    Operates on the cypher text alone; parameter values never enter the
    regex domain.
    """
    scrubbed = _scrub(cypher)
    m = _BANNED_RE.search(scrubbed)
    if m is not None:
        raise ReadOnlyViolation(
            f"RawCypher rejected: banned keyword {m.group(1)!r} in query text"
        )
