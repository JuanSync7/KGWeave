"""S22 + S23 — covergroup / coverpoint / cross promotion.

All three sub-rules are dispatched from pass 1 of ``dispatch.promote`` (the
same model used by S14/S15/S18/S22 — declarations that need to be visible to
later passes before any rule has a chance to resolve them by hierarchical
name). The metadata stubs below pin ``__rule_id__`` against the relevant
``pyslang.SyntaxKind`` values so the registry-derived Bucket-1 checklist
counts them as PROMOTE_NOW.

The parent of every Coverpoint / CoverCross is the **enclosing
CovergroupDeclaration**, not the module — pass 1 maintains a
``covergroup_stack`` alongside ``module_stack`` so the parent gid and
hierarchical path are available the moment the walker enters the cover
member. If the structural walk reaches a Coverpoint or CoverCross outside
any covergroup (which the LRM forbids but the corpus could synthesize
through a malformed bind), we fall back to the enclosing module and append
a ``leaks`` entry for diagnostics — mirroring how other rules handle their
"unexpected parent" path.

The coverpoint cover-expression is extracted via direct-child structural
scan: only the simple ``coverpoint <single_identifier> ...`` form keeps a
textual ``expr_text``; richer expressions (concatenations, ranges,
with-clauses) stay BLOB via ``expr_blob=True`` so we never serialize
arbitrary token text.

The cross member list is extracted from the SeparatedList of
``IdentifierNameSyntax`` direct children that follow the ``CrossKeyword``
token — no regex on source text. Bins inside coverpoints stay BLOB.

Planned future S-rule owners under this module (still stubs):

* CoverageBins (kept BLOB — payload-only)
"""

from __future__ import annotations

import pyslang


def _s22_covergroup(*args, **kwargs):
    """CovergroupDeclaration is promoted in pass 1 of dispatch.promote."""
    return


_s22_covergroup.__rule_id__ = "S22"


def _s23_coverpoint(*args, **kwargs):
    """Coverpoint is promoted in pass 1 of dispatch.promote."""
    return


_s23_coverpoint.__rule_id__ = "S23"


def _s23_cover_cross(*args, **kwargs):
    """CoverCross is promoted in pass 1 of dispatch.promote."""
    return


_s23_cover_cross.__rule_id__ = "S23"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.CovergroupDeclaration, _s22_covergroup),
    (pyslang.SyntaxKind.Coverpoint, _s23_coverpoint),
    (pyslang.SyntaxKind.CoverCross, _s23_cover_cross),
]
