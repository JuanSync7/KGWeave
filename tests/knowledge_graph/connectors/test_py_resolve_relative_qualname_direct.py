"""Direct unit tests for ``_resolve_relative_qualname`` (v1.12-#1).

v1.10-#2 introduced the resolver that turns ``.sibling.foo`` style
canonicals into absolute module qualnames using the consuming module's
qualname. v1.11-#3 exercised it end-to-end across multi-segment
packages, and v1.11-#1's JOURNAL flagged a latent correctness trap:
the escape-above-root case happened to land on a non-corpus-resident
qualname (e.g. ``outside.foo``) and the downstream lookup miss masked
the resolver returning a non-``None`` value. v1.12-#1 pins the
contract directly so future refactors can't regress it silently.

Contract (post v1.12-#1):

For ``consuming_module`` with ``N = len(split('.'))`` segments and a
``relative_target`` starting with ``K`` leading dots followed by an
optional ``body``:

* If ``K > N``: return ``None`` — the import escapes above the
  top-level package root.
* If ``K <= N``: retain the first ``N - K`` segments of
  ``consuming_module`` and append ``body``. When ``N - K == 0`` and
  ``body`` is non-empty, the resolved qualname is just ``body``
  (top-level). When ``body`` is empty and ``N - K > 0`` the result is
  the joined retained segments. When BOTH ``N - K == 0`` AND ``body``
  is empty, the result is ``None`` (no name to point at).

Non-relative targets (no leading dot) and an empty ``consuming_module``
both return ``None``.
"""

from __future__ import annotations

from knowledge_graph.connectors.py_scope_resolution import (
    _resolve_relative_qualname,
)


# ---------------------------------------------------------------------------
# K = 1 (same-package): retain N-1 segments + body.
# ---------------------------------------------------------------------------


def test_k1_three_segment_consumer_resolves_to_sibling_in_package() -> None:
    """N=3, K=1 → retain 2 segments, append body."""
    assert (
        _resolve_relative_qualname("a.b.c", ".sibling")
        == "a.b.sibling"
    )


def test_k1_multi_segment_body_appended_verbatim() -> None:
    """Body may itself be dotted (``from .sub.mod import x`` shape)."""
    assert (
        _resolve_relative_qualname("pkg.consumer", ".sub.mod")
        == "pkg.sub.mod"
    )


# ---------------------------------------------------------------------------
# K = 2 (parent package): retain N-2 segments + body.
# ---------------------------------------------------------------------------


def test_k2_three_segment_consumer_resolves_to_parent_package_sibling() -> None:
    """N=3, K=2 → retain 1 segment, append body."""
    assert (
        _resolve_relative_qualname("a.b.c", "..other")
        == "a.other"
    )


# ---------------------------------------------------------------------------
# K = N (top-level): retain 0 segments, body is the full result.
# ---------------------------------------------------------------------------


def test_kN_resolves_to_top_level_body() -> None:
    """N=3, K=3 → 0 segments retained → result is body (top-level)."""
    assert _resolve_relative_qualname("a.b.c", "...x") == "x"


# ---------------------------------------------------------------------------
# K = N+1 (escape above root): None. This is the v1.12-#1 key
# invariant — directly asserted, no longer hidden behind a downstream
# corpus-modules miss.
# ---------------------------------------------------------------------------


def test_kNplus1_returns_none_escape_above_root() -> None:
    """N=3, K=4 → K > N → escape above package root → None."""
    assert _resolve_relative_qualname("a.b.c", "....x") is None


def test_kNplus2_returns_none_escape_above_root() -> None:
    """N=2, K=4 → K > N → None."""
    assert _resolve_relative_qualname("a.b", "....x") is None


# ---------------------------------------------------------------------------
# Empty body cases (``from . import x``-style canonical is ``.x``,
# never ``.``; but the resolver's contract on empty body still matters
# for callers that might construct one defensively).
# ---------------------------------------------------------------------------


def test_empty_body_with_remaining_segments_returns_package_qualname() -> None:
    """N=3, K=1, body='' → retain 2 segments → joined remaining only."""
    assert _resolve_relative_qualname("a.b.c", ".") == "a.b"


def test_empty_body_with_zero_remaining_returns_none() -> None:
    """N=3, K=3, body='' → 0 remaining, nothing to point at → None."""
    assert _resolve_relative_qualname("a.b.c", "...") is None


# ---------------------------------------------------------------------------
# N=1 (top-level consumer): only K=1 is legal — that's `from . import x`
# inside a top-level file, which resolves to just ``body``.
# ---------------------------------------------------------------------------


def test_n1_top_level_consumer_k1_resolves_to_body() -> None:
    """N=1, K=1, body='x' → retain 0 → ``x`` (top-level)."""
    assert _resolve_relative_qualname("foo", ".x") == "x"


def test_n1_top_level_consumer_k2_escapes() -> None:
    """N=1, K=2 → K > N → None."""
    assert _resolve_relative_qualname("foo", "..x") is None


# ---------------------------------------------------------------------------
# Non-relative target / empty consuming module — defensive returns.
# ---------------------------------------------------------------------------


def test_non_relative_target_returns_none() -> None:
    """No leading dot → not our problem → None."""
    assert _resolve_relative_qualname("a.b.c", "absolute.x") is None


def test_empty_consuming_module_returns_none() -> None:
    """Defensive: no consumer qualname → None."""
    assert _resolve_relative_qualname("", ".x") is None
