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


def _s79_checker_instance_statement(*args, **kwargs):
    """CheckerInstanceStatement — wrapper ownership marker only.

    ``CheckerInstanceStatementSyntax`` is the procedural-scope wrapper
    pyslang emits around a ``CheckerInstantiationSyntax`` when a checker
    is instantiated from inside an ``initial`` / ``always_*`` block
    (``c_mutex u_proc (...)`` inside a procedural block parses as
    ``CheckerInstanceStatement`` whose ``.instance`` is the inner
    ``CheckerInstantiation``).

    Per ``CLAUDE.md`` lesson 5 (wrapper-kind dedup), the wrapper carries
    no independent identity — its only role is to give the inner
    instantiation a Statement-shaped slot in the procedural grammar. We
    therefore leave it as CONTAINER for structural traversal and only
    register an ownership stub here so the Bucket-1 checklist
    regenerator attributes ``CheckerInstanceStatement`` to S79 via
    ``__rule_id__`` introspection. Runtime promotion fires via the inner
    ``CheckerInstantiation`` kind (S28). No dispatch branch. Pattern
    mirrors S70 / S71 / S75 / S78.
    """
    return


_s79_checker_instance_statement.__rule_id__ = "S79"


def _s62_checker_data_declaration(*args, **kwargs):
    """CheckerDataDeclaration is promoted in pass 1 of dispatch.promote — see
    the S62 branch keyed on ``CheckerDataDeclarationSyntax``. The syntax
    surfaces only for ``rand``-prefixed checker-local data decls (plain
    ``logic x;`` inside a checker parses as DataDeclarationSyntax instead,
    handled by the existing in_data → net path under the checker_stack-
    augmented module_stack).

    Strategy: one queryable ``checker_data`` node per Declarator (S38-style
    fan-out for ``rand bit [1:0] a, b;``), attached to the enclosing checker
    via ``has_checker_data``. Attrs: data_type, has_initializer, is_rand
    (always True at this kind). Path key: ``<checker>.<name>``. The inner
    DataDeclaration wrapper is suppressed from the in_data → net path so the
    same names don't double-surface as nets — the S62 branch sets
    ``in_checker_data`` for the wrapper's subtree and the DataDeclaration
    branch short-circuits on that flag.

    This stub exists only to register the SyntaxKind under an active
    ``__rule_id__`` for the Bucket-1 checklist owner column."""
    return


_s62_checker_data_declaration.__rule_id__ = "S62"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.CheckerDeclaration, _s28_checker_declaration),
    (pyslang.SyntaxKind.CheckerInstantiation, _s28_checker_instantiation),
    (pyslang.SyntaxKind.CheckerDataDeclaration, _s62_checker_data_declaration),
    # S79: Wrapper ownership marker per lesson 5; the inner
    # CheckerInstantiation promotes via S28 in both procedural and
    # module contexts. No dispatch branch.
    (pyslang.SyntaxKind.CheckerInstanceStatement, _s79_checker_instance_statement),
]
