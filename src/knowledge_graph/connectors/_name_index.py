"""Shared name-index builder for cross-builder reference connectors.

Background
----------

The SV ↔ MD connector indexes SV declaration nodes by ``(corpus, name)``
so it can resolve MD inline-code / code-fence tokens to the right SV
node in O(1) per match. The same shape is needed by the upcoming
Python ↔ MD connector (v1.5-#3) — Python module / function / class /
imported-symbol declarations get indexed by ``(corpus, name)`` the same
way.

The grouping logic itself is generic: take a stream of
``(node_id, name, corpus)`` rows and bucket them by corpus then name.
This module factors that loop out of the SV connector so the new
connector reuses it. v1.5-#3 charter pre-req.

The SV-specific kind tuple stays here too (renamed without the leading
underscore so it's part of the documented surface). The Python builder
will define its own kind tuple in the Python connector module.
"""

from __future__ import annotations

from typing import Iterable


# Eight SV declaration kinds the SV ↔ MD connector indexes. Order is
# informational — the connector emits an edge per matching kind so name
# collisions across kinds don't silently drop. v1.3-#5 generalised the
# original module-only list to all eight.
SV_INDEXED_KINDS: tuple[str, ...] = (
    "SyntaxKind.ModuleDeclaration",
    "SyntaxKind.PackageDeclaration",
    "SyntaxKind.TypedefDeclaration",
    "SyntaxKind.ForwardTypedefDeclaration",
    "SyntaxKind.ImplicitAnsiPort",
    "SyntaxKind.ExplicitAnsiPort",
    "SyntaxKind.ImplicitNonAnsiPort",
    "SyntaxKind.ExplicitNonAnsiPort",
)


def build_name_index(
    rows: Iterable[tuple[str, str | None, str | None]],
) -> dict[str, dict[str, list[str]]]:
    """Group ``(node_id, name, corpus)`` rows into a corpus → name → ids map.

    Rows with empty or ``None`` ``name`` are skipped (they cannot be
    matched by a token-equal connector). ``corpus`` is normalised to the
    empty string when ``None`` so the outer dict has stable keys.

    The shape is intentionally a plain dict-of-dict-of-list so callers
    can mutate it (e.g. add fallback aliases) without going through an
    accessor API.
    """
    index: dict[str, dict[str, list[str]]] = {}
    for nid, name, corpus in rows:
        if not name:
            continue
        bucket = index.setdefault(corpus or "", {})
        bucket.setdefault(name, []).append(nid)
    return index


__all__ = ["SV_INDEXED_KINDS", "build_name_index"]
