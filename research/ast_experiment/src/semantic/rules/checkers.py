"""S28 — Checker declarations and checker instantiations.

Both are promoted in pass 1 of ``dispatch.promote``:

* ``CheckerDeclarationSyntax`` → role=checker, parent = enclosing
  module/package/interface (or root-anchored at compilation-unit scope),
  ``has_checker`` containment edge from the parent. The checker is also
  pushed onto the dispatch's ``module_stack`` while active so the existing
  pass-1 branches for PropertyDeclaration / SequenceDeclaration /
  ConcurrentAssertionStatement / ClockingDeclaration attach their nodes to
  the checker by hierarchical path (``c_mutex.p_mutex``, ``c_mutex.a_mutex``,
  …) without any rule-specific changes. A ``checker_stack`` is maintained
  alongside ``module_stack`` for future S-rules that want to discriminate
  "inside checker" from "inside module".

* ``CheckerInstantiationSyntax`` (the procedural-context form, wrapped by
  CheckerInstanceStatement) → role=checker_instance, parent = enclosing
  module, ``has_checker_instance`` containment edge, ``of_checker`` edge to
  the checker declaration resolved via the shared ``checker:<name>``
  name-index entry registered by the declaration branch.

Module-body checker instantiations parse as ``HierarchyInstantiationSyntax``
(pyslang cannot disambiguate from a module instantiation at parse time);
``rule_s6`` consults the same ``checker:<name>`` name-index entry in pass-2
and emits the same role / edges when the type name resolves to a checker
rather than a module/interface.

The metadata stubs below pin ``__rule_id__="S28"`` against
``pyslang.SyntaxKind.CheckerDeclaration`` and ``CheckerInstantiation`` so the
registry-derived Bucket-1 checklist counts them as PROMOTE_NOW.
"""

from __future__ import annotations

import pyslang


def _s28_checker_declaration(*args, **kwargs):
    """CheckerDeclaration is promoted in pass 1 of dispatch.promote — see the
    S28 branch. This stub exists only to register the SyntaxKind under an
    active ``__rule_id__`` for the Bucket-1 checklist."""
    return


_s28_checker_declaration.__rule_id__ = "S28"


def _s28_checker_instantiation(*args, **kwargs):
    """CheckerInstantiation is promoted in pass 1 of dispatch.promote (for the
    procedural-context form) and re-classified by rule_s6 in pass 2 (for the
    module-body HierarchyInstantiation form). See the S28 branches."""
    return


_s28_checker_instantiation.__rule_id__ = "S28"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.CheckerDeclaration, _s28_checker_declaration),
    (pyslang.SyntaxKind.CheckerInstantiation, _s28_checker_instantiation),
]
