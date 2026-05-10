# @summary
# v2 cross-reference resolver — converts a pyslang NamedValueExpression
# (or hierarchical reference) into the canonical entity name of an existing
# Signal/Port/Parameter, matching v1's <module>.<name> naming convention.
# Exports: resolve_named_value, emit_reference_triple, XREF_SOURCE
# Deps: pyslang (soft), kgweave.knowledge_graph.common
# @end-summary
"""Cross-reference resolver for the v2 dataflow walker (Wave 1, track C).

Tracks A and B emit *expression-position* nodes for every elaborated
operator / literal / statement they materialise. When such a node points at
a name (a ``NamedValueExpression`` or its hierarchical sibling), that name
must be reified as a ``references`` edge to the **already-existing** Port /
Signal / Parameter entity that v1's slang walker has produced — not as a
freshly minted node.

Public API
----------

``resolve_named_value(expr) -> tuple[str, dict] | None``
    Given a pyslang expression node, return ``(canonical_name, edge_attrs)``
    if it can be resolved to an existing entity name in the v1 naming
    scheme, else ``None``. ``edge_attrs`` is a ``dict`` of attributes the
    caller can attach to the emitted ``references`` triple.

``emit_reference_triple(subject, expr, textual_ref, source, ...) -> Triple``
    Convenience constructor that produces a fully-populated
    ``Triple(layer="ast", predicate="references", ...)``. Handles both the
    resolved and the unresolved-sentinel cases.

Naming choice
-------------

For hierarchical references (``u_inst.u_sub.internal``) the resolver
returns the **fully-qualified hierarchical path** as a single canonical
name (e.g. ``top.u_inst.u_sub.internal``). The schema doc's open-question
2 leans toward multi-hop with a query helper; we go with a single edge
because pyslang already gives us the resolved target — multi-hop walks
through Instance nodes are best done as a query-side helper. The edge
attrs include ``hop_path`` so a future helper can decompose without
re-parsing the name string.

Design notes
------------

1. Cross-references are read off pyslang's *elaborated* tree. The
   ``NamedValueExpression`` already carries a ``.symbol`` attribute
   pointing at the resolved declaration. We do **not** re-implement scope
   lookup.

2. Canonical naming exactly mirrors v1 / ``sv_connectivity.py``: every
   Signal/Port/Parameter is named by its symbol's ``hierarchicalPath``,
   stripped of whitespace. For a top-level signal that is
   ``<module>.<signal>``; for a generate-loop iteration it is
   ``<module>.<block>[<idx>].<signal>`` — exactly what v1's contains /
   data-flow walkers store.

3. Unresolved references (extern symbols, missing module bodies, parse
   failures) are surfaced via the sentinel triple: ``confidence_tier="low"``,
   ``resolved=False``, ``object`` set to the textual reference. This
   matches v1's audit-recall split.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from kgweave.knowledge_graph.common import Triple


__all__ = [
    "resolve_named_value",
    "emit_reference_triple",
    "XREF_SOURCE",
]


XREF_SOURCE = "sv_xref_resolver"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_value_reference_kind(expr: Any) -> bool:
    """Return True iff ``expr`` looks like a NamedValue / HierarchicalValue.

    Accepts both ``ExpressionKind.NamedValue`` and
    ``ExpressionKind.HierarchicalValue``. We string-match the kind because
    pyslang exposes the kind enum but its repr varies by version.
    """
    k = getattr(expr, "kind", None)
    if k is None:
        return False
    ks = str(k)
    return ks.endswith("NamedValue") or ks.endswith("HierarchicalValue")


def _hierarchical_path(symbol: Any) -> Optional[str]:
    """Return the symbol's elaborated hierarchical path, stripped.

    Returns ``None`` for symbols that have no path (synthetic / unresolved).
    """
    if symbol is None:
        return None
    path = getattr(symbol, "hierarchicalPath", None)
    if not path:
        return None
    path = str(path).strip()
    if not path:
        return None
    # pyslang sometimes prefixes with "$root." for top-level references.
    # v1 strips that — keep parity.
    if path.startswith("$root."):
        path = path[len("$root."):]
    return path or None


def _split_hop_path(canonical: str) -> List[str]:
    """Split a canonical name into its hop components, preserving ``[i]``.

    ``top.u_inst.u_sub.internal`` -> ``["top","u_inst","u_sub","internal"]``
    ``m.g[0].local_sig`` -> ``["m","g[0]","local_sig"]``
    """
    return canonical.split(".") if canonical else []


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------


def resolve_named_value(
    expr: Any,
    scope: Any = None,  # noqa: ARG001 — reserved for future scope-aware lookups
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Resolve a pyslang value-reference expression to an existing entity.

    Parameters
    ----------
    expr:
        A pyslang elaborated expression node — typically a
        ``NamedValueExpression`` or ``HierarchicalValueExpression``.
        Other kinds return ``None`` (caller should not invoke for them).
    scope:
        Reserved. The current implementation does not need extra scope
        because pyslang's elaborated symbols already carry a fully
        resolved ``hierarchicalPath``.

    Returns
    -------
    Either ``(canonical_name, edge_attrs)`` for a successfully resolved
    reference, or ``None`` if the expression is not a recognised
    value-reference shape, has no resolved symbol, or the symbol carries
    no hierarchical path. The caller should treat ``None`` as "emit the
    low-tier unresolved sentinel".
    """
    if not _is_value_reference_kind(expr):
        return None

    symbol = getattr(expr, "symbol", None)
    if symbol is None:
        return None

    canonical = _hierarchical_path(symbol)
    if canonical is None:
        return None

    hop_path = _split_hop_path(canonical)
    is_hierarchical = len(hop_path) > 2  # >2 = at least one intermediate instance

    # Best-effort: capture the symbol-kind for the consumer (Port / Variable /
    # Parameter / Genvar). We string-coerce so the value is JSON-friendly.
    sym_kind = getattr(symbol, "kind", None)
    sym_kind_str = str(sym_kind) if sym_kind is not None else ""
    # Strip the "SymbolKind." prefix for compactness.
    if sym_kind_str.startswith("SymbolKind."):
        sym_kind_str = sym_kind_str[len("SymbolKind."):]

    expr_kind_str = str(getattr(expr, "kind", ""))
    if expr_kind_str.startswith("ExpressionKind."):
        expr_kind_str = expr_kind_str[len("ExpressionKind."):]

    attrs: Dict[str, Any] = {
        "ref_kind": expr_kind_str,           # "NamedValue" / "HierarchicalValue"
        "symbol_kind": sym_kind_str,         # "Port" / "Variable" / "Parameter" ...
        "hierarchical": is_hierarchical,
        "hop_path": hop_path,
    }
    return canonical, attrs


# ---------------------------------------------------------------------------
# Triple constructor
# ---------------------------------------------------------------------------


def emit_reference_triple(
    subject: str,
    expr: Any,
    textual_ref: str,
    source: str = "",
    resolved_target: Optional[str] = None,
    attrs: Optional[Dict[str, Any]] = None,
) -> Triple:
    """Build a ``references`` Triple from an expression-position node.

    Parameters
    ----------
    subject:
        The expression-position node id (an opaque AST id minted by the
        caller — tracks A/B). The references edge is *from* this id.
    expr:
        The pyslang expression node the reference came from. Used only
        when ``resolved_target`` is not supplied — the resolver is run
        and, on failure, the low-tier sentinel is produced.
    textual_ref:
        The original source-text reference string. Used as the object of
        the sentinel triple when resolution fails (so audit views can
        still display the dangling name).
    source:
        Document path / URI propagated onto the Triple's ``source``.
    resolved_target:
        If the caller has already resolved the target, pass it in to
        avoid a second resolver call. When ``None``, the function calls
        ``resolve_named_value(expr)`` itself.
    attrs:
        Optional attribute bag from a prior ``resolve_named_value`` call.
        Currently unused in the Triple shape (Triple has fixed fields)
        but accepted so callers can pass it through without conditional
        logic; future schema work may surface select keys onto the Triple.

    Returns
    -------
    A fully-populated ``Triple`` with ``layer="ast"`` and
    ``predicate="references"``. When the reference is resolved the triple
    has ``confidence_tier="high"`` / ``resolved=True``; otherwise
    ``confidence_tier="low"`` / ``resolved=False``.
    """
    _ = attrs  # explicit no-op — see docstring
    if resolved_target is None:
        result = resolve_named_value(expr)
        if result is not None:
            resolved_target = result[0]

    if resolved_target is not None:
        return Triple(
            subject=subject,
            predicate="references",
            object=resolved_target,
            source=source,
            extractor_source=XREF_SOURCE,
            confidence=1.0,
            confidence_tier="high",
            resolved=True,
            layer="ast",
        )

    # Sentinel — unresolved.
    return Triple(
        subject=subject,
        predicate="references",
        object=textual_ref,
        source=source,
        extractor_source=XREF_SOURCE,
        confidence=0.3,
        confidence_tier="low",
        resolved=False,
        layer="ast",
    )
