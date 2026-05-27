"""Capture-resolution semantic connector for ``PyLambda`` payloads (v1.8-#3).

The Python walker (v1.7-#5) records every ``PyLambda``'s free-name
captures as a sorted ``list[str]`` under ``payload['captures']``. The
walker stays a pure structural lifter: it never asks whether a captured
name actually resolves in any enclosing lexical scope.

This connector closes that gap. Per file (per ``origin_id``) it:

1. Fetches the Origin's source bytes.
2. Re-parses with libcst and builds a *per-scope bindings index* over
   the four scope-creating CST nodes that Python defines: ``Module``,
   ``FunctionDef``, ``ClassDef``, ``Lambda``. (Comprehensions are also
   scopes but PyComprehension capture resolution is out of scope for
   this iteration — see "PyComprehension status" below.)
3. For each ``PyLambda`` row, classifies every ``captures`` entry into
   the closed set (v1.10-#1 extended 5 → 6 values)::

       {"local-in-enclosing", "module-level", "builtin",
        "cross-file-import", "module-import", "unresolved"}

   ``cross-file-import`` is emitted when a capture's module-level
   binding came from a ``from X import name`` ``PyImport`` whose origin
   module is also present in the corpus and exposes the canonical name
   at top level. The parallel ``captures_resolved`` entry then also
   carries ``origin_module: <str>`` (the qualname of the defining
   module, taken from ``PyModule.name``).

   ``module-import`` is emitted (v1.10-#1) when a capture's module-level
   binding came from an ``import X`` or ``import X.Y`` ``PyImport``
   (i.e. the captured local is the module object itself, NOT a member
   of it) AND ``X`` / ``X.Y`` is itself a corpus-resident module
   qualname. The entry also carries ``origin_module: <str>`` (the
   imported module's qualname). The two lifts are disjoint: ``from X
   import name`` shapes never produce ``module-import``; ``import X``
   shapes never produce ``cross-file-import``.

   Star-imports (``from X import *``) stay ``unresolved`` — out of
   scope.

4. Writes the result back as ``payload['captures_resolved']`` — a
   ``list[dict]`` where each entry has shape
   ``{"name": <str>, "kind": <classification>}``. The original
   ``captures`` list is preserved verbatim for back-compat.

Scope construction
------------------
A *scope* is a CST node that introduces a new local namespace. Python
recognises five: module, function (including lambdas), class, and
comprehension/generator. Names bound in a scope come from:

* **Parameters** — ``def`` and ``lambda`` formal parameters, including
  ``*args``, ``**kwargs``, positional-only and keyword-only forms.
* **Assignments** — bare ``x = ...`` and tuple/list unpacking like
  ``a, b = ...`` or ``[x, y] = ...`` (recursive).
* **Augmented assignment** — ``x += 1`` binds ``x``.
* **Annotated assignment** — ``x: int = 1`` binds ``x``.
* **Walrus** — ``(x := expr)`` binds ``x``. Per PEP 572 a walrus inside
  a comprehension binds in the *containing* function scope, but because
  we don't index comprehensions independently we treat the walrus
  target as bound in the nearest enclosing function/module scope —
  which is exactly the same answer for closure resolution purposes.
* **for-target** — ``for x in ...:`` binds ``x``.
* **with-target** — ``with f() as x:`` binds ``x``.
* **except-as** — ``except E as e:`` binds ``e`` (its scope is local to
  the handler, but treating it as function-scoped is a safe
  over-approximation — closure references after the handler are
  ``UnboundLocalError`` at runtime regardless of how we classify them).
* **Comprehension iter-targets** — only emitted on the *outer*
  enclosing scope when we don't index the comprehension itself.
* **Function / class def names** — ``def foo`` binds ``foo`` in the
  enclosing scope. Lambdas are anonymous, so they bind nothing
  themselves in their parent.
* **Imports** — ``import x as y`` binds ``y`` (or ``x`` if no alias);
  ``from m import a, b as c`` binds ``a`` and ``c``.
* **nonlocal** — declares the name as resolved in an enclosing
  function scope. Recorded on the inner scope so that lambdas nested
  inside this scope see the name as locally bound (which is the
  correct answer: ``nonlocal`` *is* a local-in-enclosing reference).
* **global** — declares the name as module-scoped. Recorded on the
  inner scope so the local body's lambdas see it as locally bound;
  we *also* trust that it exists at module level (or is a builtin)
  for the classification of outer lambdas.

**Class scope is opaque to inner functions.** Standard Python scoping:
methods do NOT see class-body names through enclosing-scope lookup —
they see module-level. We honour that by skipping ``ClassDef`` when
walking *upwards* from a lambda to gather enclosing scopes, unless
the immediate parent of the lambda is the class itself (the class
suite is in scope while the body is being executed but not while a
method body is). Since lambdas are never at class-body-only positions
except as defaults/value expressions evaluated at class-definition
time, treating ClassDef as transparent to *direct* children but
opaque to nested function/lambda children matches CPython's lookup
order.

PyComprehension status
----------------------
PyComprehension capture-equivalent (free names referenced in comp body
that aren't comp-bound iter-targets) is **deferred to v1.9**. The
walker never records comprehension captures today — only iter-targets
shape the comp's runtime semantics, and the parent-scope is recorded
via PARENT_OF. Adding a separate captures field for comprehensions
would require an additional walker payload addition, which is out of
scope for a connector-only v1.8 item. Choice documented in the
v1.8-#3 retro.

Builtin set
-----------
We use ``set(dir(builtins))`` minus dunder names. ``builtins.__all__``
exists but is incomplete (it omits e.g. ``True``, ``False``, ``None``,
and many ``__build_class__``-style helpers). ``dir(builtins)`` is the
authoritative live list; dropping dunders removes ``__name__``,
``__doc__``, ``__build_class__`` and friends that are never written
in user source. Choice documented in retro.

Persistence
-----------
Node ``payload`` is a single JSON STRING on the Node table. The
connector reads, mutates the inner ``payload`` dict to add
``captures_resolved``, and writes the JSON back via
``SET n.payload = $payload``. Idempotent: a second run produces
identical output.
"""

from __future__ import annotations

import builtins as _builtins
import json
from typing import Any

import libcst as cst
from libcst.metadata import ByteSpanPositionProvider, MetadataWrapper

from knowledge_graph.store.snapshot import BYTES_CODEC


# Closed classification set (v1.10-#1: extended 5 -> 6).
KIND_LOCAL_ENCLOSING = "local-in-enclosing"
KIND_MODULE_LEVEL = "module-level"
KIND_BUILTIN = "builtin"
KIND_CROSS_FILE_IMPORT = "cross-file-import"
KIND_MODULE_IMPORT = "module-import"
KIND_UNRESOLVED = "unresolved"


def _builtin_names() -> frozenset[str]:
    """Return the curated set of Python builtin identifiers.

    ``dir(builtins)`` is the live source; we strip dunders (``__x__``)
    because those are never written as bare identifiers in user code
    and would otherwise dilute the set.
    """
    return frozenset(
        n for n in dir(_builtins) if not (n.startswith("__") and n.endswith("__"))
    )


_BUILTINS: frozenset[str] = _builtin_names()


# ---------------------------------------------------------------------------
# Scope index construction (libcst pass)
# ---------------------------------------------------------------------------

# A "scope frame" is one entry in the enclosing-scope stack:
#   ("module" | "function" | "class" | "lambda", bindings: set[str])
# We also remember the lambda's byte span when the frame is a lambda
# so we can map back to the DB row.


def _names_bound_by_assign_target(target: cst.BaseExpression) -> list[str]:
    """Collect names bound by an assignment LHS (recursive unpack).

    Handles bare ``Name``, ``Tuple``, ``List``, ``StarredElement`` and
    any nesting thereof. Attribute / subscript targets bind nothing
    new in the local namespace (they mutate an existing object).
    """
    out: list[str] = []

    def walk(node: cst.CSTNode) -> None:
        if isinstance(node, cst.Name):
            out.append(node.value)
            return
        if isinstance(node, (cst.Tuple, cst.List)):
            for el in node.elements:
                walk(el)
            return
        if isinstance(node, (cst.Element, cst.StarredElement)):
            walk(node.value)
            return
        # Attribute / Subscript / others: not a fresh binding.

    walk(target)
    return out


def _param_names(params: cst.Parameters) -> list[str]:
    out: list[str] = []
    for p in (
        list(params.posonly_params)
        + list(params.params)
        + list(params.kwonly_params)
    ):
        out.append(p.name.value)
    if isinstance(params.star_arg, cst.Param):
        out.append(params.star_arg.name.value)
    if params.star_kwarg is not None:
        out.append(params.star_kwarg.name.value)
    return out


def _import_bindings(stmt: cst.BaseSmallStatement) -> list[str]:
    """Names bound by an ``import`` / ``from ... import`` small stmt."""
    out: list[str] = []
    if isinstance(stmt, cst.Import):
        for alias in stmt.names:
            if alias.asname is not None and isinstance(
                alias.asname.name, cst.Name
            ):
                out.append(alias.asname.name.value)
            else:
                # `import a.b.c` binds `a` in the local namespace.
                name = alias.name
                while isinstance(name, cst.Attribute):
                    name = name.value
                if isinstance(name, cst.Name):
                    out.append(name.value)
    elif isinstance(stmt, cst.ImportFrom):
        if isinstance(stmt.names, cst.ImportStar):
            return out  # opaque
        for alias in stmt.names:
            if alias.asname is not None and isinstance(
                alias.asname.name, cst.Name
            ):
                out.append(alias.asname.name.value)
            elif isinstance(alias.name, cst.Name):
                out.append(alias.name.value)
    return out


def _bindings_in_block(
    body: cst.BaseSuite | cst.Module,
) -> tuple[set[str], set[str], set[str]]:
    """Walk a function/module/class suite (NOT crossing nested scopes).

    Returns ``(local_bindings, nonlocal_decls, global_decls)`` collected
    over the suite. ``FunctionDef`` / ``ClassDef`` / ``Lambda`` /
    comprehensions are visited but not recursed into — we only want the
    bindings introduced in THIS scope.
    """
    locals_: set[str] = set()
    nonlocals_: set[str] = set()
    globals_: set[str] = set()

    def add_target(target: cst.BaseExpression) -> None:
        for n in _names_bound_by_assign_target(target):
            locals_.add(n)

    def walk_for_walrus(node: cst.CSTNode) -> None:
        # Walrus assignments bubble up across most expressions but stop
        # at scope-introducing constructs.
        if isinstance(node, (cst.FunctionDef, cst.ClassDef, cst.Lambda)):
            return
        if isinstance(
            node, (cst.ListComp, cst.SetComp, cst.DictComp, cst.GeneratorExp)
        ):
            # PEP 572: walrus in comprehension binds in enclosing scope.
            # Walk it but skip the comp's own scope-creating bits.
            for child in node.children:
                walk_for_walrus(child)
            return
        if isinstance(node, cst.NamedExpr):
            if isinstance(node.target, cst.Name):
                locals_.add(node.target.value)
        for child in node.children:
            walk_for_walrus(child)

    def visit(node: cst.CSTNode) -> None:
        # Skip into nested scope-creators without descending their bodies.
        if isinstance(node, cst.FunctionDef):
            locals_.add(node.name.value)
            # Decorators and default-value exprs evaluate in THIS scope,
            # but they don't introduce new bindings — skip body, do not
            # recurse further.
            return
        if isinstance(node, cst.ClassDef):
            locals_.add(node.name.value)
            return
        if isinstance(node, cst.Lambda):
            return
        if isinstance(
            node, (cst.ListComp, cst.SetComp, cst.DictComp, cst.GeneratorExp)
        ):
            # Comprehension is its own scope — its iter targets don't
            # bind here. BUT a walrus inside still bubbles up.
            walk_for_walrus(node)
            return

        if isinstance(node, cst.Assign):
            for tgt in node.targets:
                add_target(tgt.target)
            walk_for_walrus(node.value)
            return
        if isinstance(node, cst.AugAssign):
            add_target(node.target)
            walk_for_walrus(node.value)
            return
        if isinstance(node, cst.AnnAssign):
            add_target(node.target)
            if node.value is not None:
                walk_for_walrus(node.value)
            return
        if isinstance(node, cst.NamedExpr):
            if isinstance(node.target, cst.Name):
                locals_.add(node.target.value)
            walk_for_walrus(node.value)
            return
        if isinstance(node, cst.For):
            add_target(node.target)
            walk_for_walrus(node.iter)
            for child in node.body.children:
                visit(child)
            if node.orelse is not None:
                for child in node.orelse.body.children:
                    visit(child)
            return
        if isinstance(node, cst.With):
            for item in node.items:
                if item.asname is not None:
                    add_target(item.asname.name)
            for child in node.body.children:
                visit(child)
            return
        if isinstance(node, cst.Try):
            for child in node.body.children:
                visit(child)
            for handler in node.handlers:
                if handler.name is not None and isinstance(
                    handler.name.name, cst.Name
                ):
                    locals_.add(handler.name.name.value)
                for child in handler.body.children:
                    visit(child)
            if node.orelse is not None:
                for child in node.orelse.body.children:
                    visit(child)
            if node.finalbody is not None:
                for child in node.finalbody.body.children:
                    visit(child)
            return
        if isinstance(node, cst.If):
            walk_for_walrus(node.test)
            for child in node.body.children:
                visit(child)
            orelse = node.orelse
            while orelse is not None:
                if isinstance(orelse, cst.If):
                    walk_for_walrus(orelse.test)
                    for child in orelse.body.children:
                        visit(child)
                    orelse = orelse.orelse
                elif isinstance(orelse, cst.Else):
                    for child in orelse.body.children:
                        visit(child)
                    orelse = None
                else:
                    orelse = None
            return
        if isinstance(node, cst.While):
            walk_for_walrus(node.test)
            for child in node.body.children:
                visit(child)
            if node.orelse is not None:
                for child in node.orelse.body.children:
                    visit(child)
            return
        if isinstance(node, cst.Global):
            for nm in node.names:
                globals_.add(nm.name.value)
            return
        if isinstance(node, cst.Nonlocal):
            for nm in node.names:
                nonlocals_.add(nm.name.value)
            return
        if isinstance(node, (cst.Import, cst.ImportFrom)):
            for n in _import_bindings(node):
                locals_.add(n)
            return

        # Default: recurse children, but watch for walrus.
        if isinstance(node, cst.NamedExpr):
            walk_for_walrus(node)
            return
        for child in node.children:
            visit(child)

    # ``body`` may be a Module, IndentedBlock, or SimpleStatementSuite.
    children = body.children if hasattr(body, "children") else []
    for child in children:
        visit(child)
    return locals_, nonlocals_, globals_


def _comp_iter_target_names(target: cst.BaseExpression) -> list[str]:
    """Names bound by a CompFor target (recursive unpack).

    Mirrors :func:`_names_bound_by_assign_target` but kept separate so
    the comprehension-scope construction here is self-contained.
    """
    out: list[str] = []

    def walk(node: cst.CSTNode) -> None:
        if isinstance(node, cst.Name):
            out.append(node.value)
            return
        if isinstance(node, (cst.Tuple, cst.List)):
            for el in node.elements:
                walk(el)
            return
        if isinstance(node, (cst.Element, cst.StarredElement)):
            walk(node.value)
            return

    walk(target)
    return out


def _comprehension_local_names(comp: cst.CSTNode) -> set[str]:
    """All names bound by a comprehension's own scope (iter-targets).

    Walrus targets inside a comp are NOT classified as comp-local for
    closure-resolution purposes (PEP 572 sends them to the enclosing
    function), but the walker already subtracted walrus targets from
    the ``captures`` list it shipped, so the connector never sees them
    here. Iter-targets alone suffice.
    """
    out: set[str] = set()
    for_in = getattr(comp, "for_in", None)
    while isinstance(for_in, cst.CompFor):
        for n in _comp_iter_target_names(for_in.target):
            out.add(n)
        for_in = for_in.inner_for_in
    return out


class _LambdaScopeIndexer(cst.CSTVisitor):
    """Walk a module and record per-lambda / per-comprehension scopes.

    For every ``Lambda`` / ``ListComp`` / ``SetComp`` / ``DictComp`` /
    ``GeneratorExp`` encountered we capture:

    * its byte span (start, end) — for matching back to DB rows
    * its own locally-bound names (lambda params / comp iter-targets)
    * the bindings of every enclosing FunctionDef / Lambda /
      Comprehension
    * the bindings of the Module
    * whether any enclosing scope is a class (which is *opaque* to
      nested closures for closure-name lookup, per Python scoping)

    Walking is depth-first; we push/pop a stack frame on every
    scope-creating node.

    Generalises the original v1.8-#3 lambda-only indexer to cover
    comprehensions as well (v1.9-#1). The class name is retained for
    back-compat — ``self.lambdas`` and ``self.comprehensions`` give
    span-keyed frames per kind.
    """

    METADATA_DEPENDENCIES = (ByteSpanPositionProvider,)

    def __init__(self, module: cst.Module) -> None:
        super().__init__()
        self._module = module
        self._stack: list[dict[str, Any]] = []
        # span -> {"enclosing_locals": list[set[str]], "module_locals": set[str]}
        self.lambdas: dict[tuple[int, int], dict[str, Any]] = {}
        self.comprehensions: dict[tuple[int, int], dict[str, Any]] = {}
        self._module_locals: set[str] = set()
        # Precompute module-level bindings once.
        mloc, _, _ = _bindings_in_block(module)
        self._module_locals = mloc

    # --- scope push/pop ---------------------------------------------------

    def visit_Module(self, node: cst.Module) -> None:
        self._stack.append(
            {
                "kind": "module",
                "locals": self._module_locals,
                "nonlocals": set(),
                "globals": set(),
            }
        )

    def leave_Module(self, original_node: cst.Module) -> None:
        self._stack.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        body_locals, nonlocals, globals_ = _bindings_in_block(node.body)
        params = set(_param_names(node.params))
        self._stack.append(
            {
                "kind": "function",
                "locals": body_locals | params,
                "nonlocals": nonlocals,
                "globals": globals_,
            }
        )

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self._stack.pop()

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        body_locals, nonlocals, globals_ = _bindings_in_block(node.body)
        self._stack.append(
            {
                "kind": "class",
                "locals": body_locals,
                "nonlocals": nonlocals,
                "globals": globals_,
            }
        )

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self._stack.pop()

    def visit_Lambda(self, node: cst.Lambda) -> None:
        params = set(_param_names(node.params))
        # Walrus in lambda body would bind in enclosing function scope,
        # but the walker already excludes such targets from the
        # capture list (walrus assigns a Name load on lookup); we don't
        # need to enumerate them in the lambda frame itself.
        self._record_scope(node, self.lambdas, params)
        self._stack.append(
            {
                "kind": "lambda",
                "locals": params,
                "nonlocals": set(),
                "globals": set(),
            }
        )

    def leave_Lambda(self, original_node: cst.Lambda) -> None:
        self._stack.pop()

    # --- comprehension scopes (v1.9-#1) ----------------------------------

    def _enter_comp(self, node: cst.CSTNode) -> None:
        locals_ = _comprehension_local_names(node)
        self._record_scope(node, self.comprehensions, locals_)
        self._stack.append(
            {
                "kind": "comprehension",
                "locals": locals_,
                "nonlocals": set(),
                "globals": set(),
            }
        )

    def _leave_comp(self) -> None:
        self._stack.pop()

    def visit_ListComp(self, node: cst.ListComp) -> None:
        self._enter_comp(node)

    def leave_ListComp(self, original_node: cst.ListComp) -> None:
        self._leave_comp()

    def visit_SetComp(self, node: cst.SetComp) -> None:
        self._enter_comp(node)

    def leave_SetComp(self, original_node: cst.SetComp) -> None:
        self._leave_comp()

    def visit_DictComp(self, node: cst.DictComp) -> None:
        self._enter_comp(node)

    def leave_DictComp(self, original_node: cst.DictComp) -> None:
        self._leave_comp()

    def visit_GeneratorExp(self, node: cst.GeneratorExp) -> None:
        self._enter_comp(node)

    def leave_GeneratorExp(self, original_node: cst.GeneratorExp) -> None:
        self._leave_comp()

    # --- recording --------------------------------------------------------

    def _record_scope(
        self,
        node: cst.CSTNode,
        bucket: dict[tuple[int, int], dict[str, Any]],
        locals_: set[str],
    ) -> None:
        """Snapshot the current enclosing-scope stack for ``node``.

        Used for both lambdas (recording into ``self.lambdas``) and
        comprehensions (recording into ``self.comprehensions``). The
        frame snapshot is keyed by byte span so the connector can
        later match it to the corresponding PyLambda / PyComprehension
        DB row.
        """
        span = self.get_metadata(ByteSpanPositionProvider, node, None)
        if span is None:
            return
        # Collect enclosing scopes (excluding the not-yet-pushed frame).
        # Order: innermost-first.
        enclosing_locals: list[set[str]] = []
        enclosing_nonlocals: list[set[str]] = []
        enclosing_globals: list[set[str]] = []
        enclosing_kinds: list[str] = []
        for frame in reversed(self._stack):
            enclosing_locals.append(frame["locals"])
            enclosing_nonlocals.append(frame["nonlocals"])
            enclosing_globals.append(frame["globals"])
            enclosing_kinds.append(frame["kind"])
        bucket[(span.start, span.start + span.length)] = {
            "params": locals_,
            "enclosing_locals": enclosing_locals,
            "enclosing_nonlocals": enclosing_nonlocals,
            "enclosing_globals": enclosing_globals,
            "enclosing_kinds": enclosing_kinds,
            "module_locals": self._module_locals,
        }


def _classify(name: str, frame: dict[str, Any]) -> str:
    """Classify ``name`` against the enclosing-scope frame.

    Resolution order mirrors CPython's LEGB with class-scope opacity:

    1. **Enclosing functions / lambdas** (innermost-first), skipping
       class scopes — methods can't close over class-body names. A
       match in any of these scopes (including ``nonlocal``-declared
       names, which are also recorded as locals on the *inner* scope
       that declared them) yields ``local-in-enclosing``.
    2. **Module** — ``module-level``. Also: if the name is declared
       ``global`` in any enclosing scope, that's still a module-level
       reference for closure semantics.
    3. **Builtin** — ``builtin`` from the curated set.
    4. Otherwise — ``unresolved``.
    """
    enclosing_locals = frame["enclosing_locals"]
    enclosing_nonlocals = frame["enclosing_nonlocals"]
    enclosing_globals = frame["enclosing_globals"]
    enclosing_kinds = frame["enclosing_kinds"]
    module_locals: set[str] = frame["module_locals"]

    # Pass 1: enclosing functions / lambdas, skipping classes; module
    # frame is handled separately below.
    for locs, nonlocs, globs, kind in zip(
        enclosing_locals,
        enclosing_nonlocals,
        enclosing_globals,
        enclosing_kinds,
    ):
        if kind == "class":
            # Opaque to nested function/lambda closure lookup.
            continue
        if kind == "module":
            # Reached module without a match; defer to module pass below.
            break
        # function or lambda
        if name in nonlocs:
            return KIND_LOCAL_ENCLOSING
        if name in globs:
            # Declared global here -> resolve via module, not local.
            if name in module_locals:
                return KIND_MODULE_LEVEL
            if name in _BUILTINS:
                return KIND_BUILTIN
            return KIND_UNRESOLVED
        if name in locs:
            return KIND_LOCAL_ENCLOSING

    # Pass 2: module scope.
    if name in module_locals:
        return KIND_MODULE_LEVEL

    # Pass 3: builtins.
    if name in _BUILTINS:
        return KIND_BUILTIN

    return KIND_UNRESOLVED


# ---------------------------------------------------------------------------
# Cross-file index construction (v1.9-#3)
# ---------------------------------------------------------------------------


def _build_module_exports(conn) -> dict[str, set[str]]:
    """Corpus-wide ``{module_qualname: set[exported_name]}`` index.

    A *module qualname* is ``PyModule.name`` (the writer sets this to
    the package-qualified module name when an ancestor ``__init__.py``
    is present, falling back to the file stem otherwise — see
    ``builders/py/writer.py::_module_qualname`` and
    ``_resolve_name``). An
    *exported name* is any top-level (parent is the ``PyModule``)
    ``PyFunction`` / ``PyClass`` declaration, plus the locally-bound
    names of any ``PyImport`` re-export (``from x import foo`` makes
    ``foo`` a name in this module's surface even though it originated
    elsewhere). Star-imports contribute nothing to the export set —
    their bindings are not statically knowable here (v1.9-#3 scope).

    Implementation pulls the data via two Cypher queries: one for
    PyFunction/PyClass children of PyModule, one for PyImport rows
    parented to a PyModule (their ``aliases`` payload gives the local
    bindings). Both run once per connector invocation.
    """
    exports: dict[str, set[str]] = {}

    # Top-level PyFunction / PyClass children of any PyModule.
    res = conn.execute(
        """
        MATCH (m:Node)-[:PARENT_OF]->(c:Node)
        WHERE m.source = 'py' AND m.kind = 'PyModule'
          AND c.source = 'py' AND c.kind IN ['PyFunction', 'PyClass']
        RETURN m.name AS mname, c.name AS cname
        """,
        {},
    )
    while res.has_next():
        row = res.get_next()
        mname, cname = row[0], row[1]
        if not mname or not cname:
            continue
        exports.setdefault(mname, set()).add(cname)

    # PyImport rows parented to a PyModule contribute their local
    # bindings (``aliases`` keys) as re-exports.
    res = conn.execute(
        """
        MATCH (m:Node)-[:PARENT_OF]->(i:Node)
        WHERE m.source = 'py' AND m.kind = 'PyModule'
          AND i.source = 'py' AND i.kind = 'PyImport'
          AND i.payload IS NOT NULL
        RETURN m.name AS mname, i.payload AS pl
        """,
        {},
    )
    while res.has_next():
        row = res.get_next()
        mname, pl = row[0], row[1]
        if not mname or not pl:
            continue
        try:
            payload_obj = json.loads(pl)
        except (TypeError, ValueError):
            continue
        inner = payload_obj.get("payload")
        if not isinstance(inner, dict):
            continue
        aliases = inner.get("aliases")
        if not isinstance(aliases, dict):
            continue
        for local_name in aliases:
            if isinstance(local_name, str) and local_name:
                exports.setdefault(mname, set()).add(local_name)

    return exports


def _imports_for_origin(conn, origin_id: str) -> dict[str, str]:
    """Return ``{local_name: canonical_dotted_name}`` for one consuming
    file's ``PyImport`` rows.

    Aggregates every ``PyImport.payload.aliases`` map that belongs to
    this ``origin_id``. Star-import rows carry an empty aliases dict
    (walker convention) so they contribute nothing here — they are
    expanded separately by :func:`_star_imports_for_origin` /
    :func:`_expand_star_imports` (v1.10-#3).
    """
    out: dict[str, str] = {}
    res = conn.execute(
        """
        MATCH (i:Node)
        WHERE i.source = 'py' AND i.kind = 'PyImport'
          AND i.origin_id = $oid AND i.payload IS NOT NULL
        RETURN i.payload AS pl
        """,
        {"oid": origin_id},
    )
    while res.has_next():
        pl = res.get_next()[0]
        if not pl:
            continue
        try:
            payload_obj = json.loads(pl)
        except (TypeError, ValueError):
            continue
        inner = payload_obj.get("payload")
        if not isinstance(inner, dict):
            continue
        aliases = inner.get("aliases")
        if not isinstance(aliases, dict):
            continue
        for local_name, canonical in aliases.items():
            if isinstance(local_name, str) and isinstance(canonical, str):
                out[local_name] = canonical
    return out


def _star_imports_for_origin(conn, origin_id: str) -> list[str]:
    """Return the list of origin module qualnames star-imported by one
    consuming file (v1.10-#3).

    A row counts as a star-import iff its payload has ``is_star: True``
    (walker contract; missing key treated as False for back-compat).
    Relative star-imports (``from . import *``) currently keep their
    leading-dot module form; downstream lookup against
    ``module_exports`` naturally misses them, matching the v1.10-#2
    "no relative-package resolution yet" stance.
    """
    out: list[str] = []
    res = conn.execute(
        """
        MATCH (i:Node)
        WHERE i.source = 'py' AND i.kind = 'PyImport'
          AND i.origin_id = $oid AND i.payload IS NOT NULL
        RETURN i.payload AS pl
        """,
        {"oid": origin_id},
    )
    while res.has_next():
        pl = res.get_next()[0]
        if not pl:
            continue
        try:
            payload_obj = json.loads(pl)
        except (TypeError, ValueError):
            continue
        inner = payload_obj.get("payload")
        if not isinstance(inner, dict):
            continue
        if not bool(inner.get("is_star", False)):
            continue
        module_name = inner.get("module")
        if isinstance(module_name, str) and module_name:
            out.append(module_name)
    return out


def _build_module_all_index(conn) -> dict[str, list[str]]:
    """Corpus-wide ``{module_qualname: list[name]}`` for modules with a
    literal top-level ``__all__`` (v1.10-#3).

    Walker stores the parsed ``__all__`` list under
    ``PyModule.payload.all_exports`` (see ``walker._extract_dunder_all``).
    Modules without ``__all__`` are absent from this map; star-import
    expansion then falls back to the "no underscore" public-export rule.
    """
    out: dict[str, list[str]] = {}
    res = conn.execute(
        """
        MATCH (m:Node)
        WHERE m.source = 'py' AND m.kind = 'PyModule'
          AND m.payload IS NOT NULL AND m.name IS NOT NULL
        RETURN m.name AS mname, m.payload AS pl
        """,
        {},
    )
    while res.has_next():
        row = res.get_next()
        mname, pl = row[0], row[1]
        if not mname or not pl:
            continue
        try:
            payload_obj = json.loads(pl)
        except (TypeError, ValueError):
            continue
        inner = payload_obj.get("payload")
        if not isinstance(inner, dict):
            continue
        all_exports = inner.get("all_exports")
        if not isinstance(all_exports, list):
            continue
        names = [n for n in all_exports if isinstance(n, str) and n]
        out[mname] = names
    return out


def _expand_star_imports(
    star_origins: list[str],
    module_exports: dict[str, set[str]],
    module_all_index: dict[str, list[str]],
    base_imports: dict[str, str],
) -> dict[str, str]:
    """Expand each star-import origin into ``{local_name: canonical}``
    entries (v1.10-#3).

    For each star-import target module ``X``:

    * If ``X`` declares ``__all__`` (corpus-resident with a literal
      ``__all__`` list), use exactly that list.
    * Else if ``X`` is corpus-resident, use every export of ``X`` whose
      name does NOT start with an underscore (PEP 8 public).
    * Else (``X`` not in the corpus), contribute nothing — captures
      that would have flowed through stay ``unresolved``.

    Named imports in ``base_imports`` win over star-import expansions —
    if a local name is already bound by an explicit import, the star
    must not shadow it. This matches Python's actual import semantics:
    ``from X import *`` only binds names not already bound.
    """
    expanded = dict(base_imports)
    for origin in star_origins:
        if origin in module_all_index:
            names = module_all_index[origin]
        else:
            exports = module_exports.get(origin)
            if exports is None:
                continue
            names = [n for n in exports if not n.startswith("_")]
        for name in names:
            if name in expanded:
                continue
            expanded[name] = f"{origin}.{name}"
    return expanded


def _build_corpus_modules(conn) -> set[str]:
    """Return the set of every ``PyModule.name`` in the corpus.

    Used by v1.10-#1's ``module-import`` lift: an ``import X`` capture
    is lifted only when ``X`` matches one of these qualnames (i.e. the
    imported module is corpus-resident). Out-of-corpus imports (stdlib,
    third-party) stay ``unresolved``.
    """
    out: set[str] = set()
    res = conn.execute(
        """
        MATCH (m:Node)
        WHERE m.source = 'py' AND m.kind = 'PyModule' AND m.name IS NOT NULL
        RETURN m.name AS mname
        """,
        {},
    )
    while res.has_next():
        mname = res.get_next()[0]
        if isinstance(mname, str) and mname:
            out.add(mname)
    return out


def _resolve_relative_qualname(
    consuming_module: str, relative_target: str
) -> str | None:
    """Resolve a leading-dot relative import canonical to an absolute qualname.

    v1.8-#1 records relative imports' canonical name with leading dots
    preserved (``from .sibling import foo`` → ``.sibling.foo``;
    ``from ..pkg.thing import x`` → ``..pkg.thing.x``). v1.10-#2 turns
    that into an absolute qualname using the consuming module's package
    path. v1.12-#1 pins the contract:

    Let ``N = len(consuming_module.split('.'))`` and ``K`` the count of
    leading dots in ``relative_target``, with the remainder being the
    optional ``body``:

    * **K > N** — the relative escapes above the top-level package
      root: return ``None``. This is the v1.12-#1 invariant — directly
      enforced here rather than hidden behind a downstream corpus
      lookup miss.
    * **K ≤ N** — retain the first ``N - K`` segments of
      ``consuming_module`` and append ``body``. Edge cases:
        - ``N - K > 0`` and ``body`` non-empty → join + dot + body.
        - ``N - K == 0`` and ``body`` non-empty → ``body`` (top-level).
        - ``N - K > 0`` and ``body`` empty → joined retained segments
          (the package qualname itself).
        - ``N - K == 0`` and ``body`` empty → ``None`` (no target).

    Worked examples (consuming = ``pkg.sub.consumer``, N=3):

    * ``.sibling.foo``   (K=1) → ``pkg.sub.sibling.foo``
    * ``..other.bar``    (K=2) → ``pkg.other.bar``
    * ``...x``           (K=3) → ``x`` (legitimate top-level)
    * ``....x``          (K=4) → ``None`` (escape above root)

    Defensive: a non-dotted ``relative_target`` or an empty
    ``consuming_module`` both return ``None``.

    Note on ``__init__.py`` consumers: since v1.11-#1 the
    ``PyModule.name`` of ``pkg/__init__.py`` is ``pkg`` (the package
    qualname). Under the ``N - K`` rule, ``from .x import y`` inside
    ``pkg/__init__.py`` (N=1, K=1, body='x.y') resolves to ``x.y``
    (top-level) — not to ``pkg.x.y``. Practical impact in the current
    corpus is nil (no fixture exercises this shape), but consumers
    that care should special-case the convention upstream.
    """
    if not relative_target.startswith("."):
        return None
    if not consuming_module:
        return None
    # Count leading dots.
    k = 0
    for ch in relative_target:
        if ch == ".":
            k += 1
        else:
            break
    body = relative_target[k:]
    segments = consuming_module.split(".")
    n = len(segments)
    if k > n:
        # Legitimate escape above package root.
        return None
    retained = segments[: n - k]  # N-K segments; [] when K == N.
    if retained and body:
        return ".".join(retained) + "." + body
    if retained:
        return ".".join(retained)
    if body:
        return body
    # K == N and body empty — nothing to point at.
    return None


def _lift_to_module_import(
    name: str,
    imports: dict[str, str],
    corpus_modules: set[str],
    consuming_module: str = "",
) -> tuple[str, str | None]:
    """Try to lift ``name`` to ``module-import`` (v1.10-#1).

    Returns ``(kind, origin_module)``. ``origin_module`` is set only
    when ``kind == "module-import"``. If the lift fails the caller
    should try ``_lift_to_cross_file`` next, then fall back to
    ``unresolved``.

    Lift rules:

    * ``name`` must appear in ``imports`` (the consuming file's
      ``PyImport.aliases`` rollup).
    * The canonical form must be a bare ``import X`` shape — either
      ``X`` (no dots) OR ``X.Y[.Z...]`` where the LOCAL binding is the
      module's full canonical name (i.e. ``import a.b`` with no
      ``as`` binds ``a`` locally, canonical ``a.b``; the captured
      name is the top-level segment ``a``). We detect this by checking
      that the canonical name itself is in ``corpus_modules`` — that
      is, the imported thing IS a module, not a member.
    * ``from X import name`` shapes are deliberately excluded: in those
      cases the canonical is ``X.name`` where ``X`` is the module and
      ``name`` is a member of it; ``X.name`` would not be a module
      qualname (no PyModule with that name exists), so the corpus-
      modules check naturally rejects them.

    The two-lift architecture means ``module-import`` and
    ``cross-file-import`` are disjoint by construction.
    """
    canonical = imports.get(name)
    if not canonical:
        return KIND_UNRESOLVED, None
    # v1.10-#2: relative-import canonicals start with one or more dots
    # (``.sibling``, ``..pkg``). Resolve to an absolute qualname using
    # the consuming module's package path before the corpus-modules
    # lookup. If resolution fails (escape above package root) we fall
    # through to ``unresolved``.
    if canonical.startswith("."):
        resolved = _resolve_relative_qualname(consuming_module, canonical)
        if resolved is None:
            return KIND_UNRESOLVED, None
        canonical = resolved
    # An ``import X`` binding has the LOCAL name equal to the top-level
    # segment of canonical. For ``from X import leaf`` the LOCAL is
    # ``leaf`` and canonical is ``X.leaf`` — top-level segment is ``X``,
    # which is NOT the local. We disambiguate purely on whether the
    # canonical name itself is a corpus-resident module qualname; that
    # is true for ``import X`` / ``import X.Y`` only.
    if canonical not in corpus_modules:
        return KIND_UNRESOLVED, None
    return KIND_MODULE_IMPORT, canonical


def _lift_to_cross_file(
    name: str,
    imports: dict[str, str],
    module_exports: dict[str, set[str]],
    consuming_module: str = "",
) -> tuple[str, str | None]:
    """Try to lift ``name`` to ``cross-file-import``.

    Returns ``(kind, origin_module)``. ``origin_module`` is set only
    when ``kind == "cross-file-import"``. If the lift fails the caller
    should fall back to ``unresolved``.

    Lift rules:

    * ``name`` must appear in ``imports`` (the consuming file's
      ``PyImport.aliases`` rollup).
    * The canonical form must be ``"<module>.<leaf>"`` — i.e. a
      ``from m import leaf`` style. Plain ``import a`` / ``import a.b``
      bindings give canonical ``"a"`` / ``"a.b"`` with the local being
      the top-level segment; capturing those means referencing the
      *module object* itself, not a member, so we do NOT lift those.
    * ``<module>`` must be in ``module_exports`` AND ``<leaf>`` must be
      in that module's export set.

    Relative imports keep their leading dots in the canonical form
    (``.pkg.foo``); the dotted-module lookup naturally misses for
    them (no PyModule has a leading-dot name), so they fall through to
    ``unresolved``. That's the safe answer until v1.10 wires package
    resolution.
    """
    canonical = imports.get(name)
    if not canonical:
        return KIND_UNRESOLVED, None
    # v1.10-#2: relative canonicals (``.sibling.foo``, ``..pkg.x``)
    # need package-path resolution before the ``module.leaf`` split
    # below. Resolve using the consuming module's qualname; on escape
    # above the package root, fall through to ``unresolved``.
    if canonical.startswith("."):
        resolved = _resolve_relative_qualname(consuming_module, canonical)
        if resolved is None:
            return KIND_UNRESOLVED, None
        canonical = resolved
    if "." not in canonical:
        # Plain ``import a`` — captured name is the module object.
        # Not a cross-file member reference; stay unresolved.
        return KIND_UNRESOLVED, None
    origin_module, _, leaf = canonical.rpartition(".")
    if not origin_module or not leaf:
        return KIND_UNRESOLVED, None
    exports = module_exports.get(origin_module)
    if exports is None or leaf not in exports:
        return KIND_UNRESOLVED, None
    return KIND_CROSS_FILE_IMPORT, origin_module


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------


class PyScopeResolutionConnector:
    """Classify every ``PyLambda`` capture against lexical scopes.

    Reads ``payload['captures']`` (set by the walker), classifies each
    name into ``{local-in-enclosing, module-level, builtin, unresolved}``
    by re-parsing the file's source and walking its scope tree, and
    writes the parallel list ``payload['captures_resolved']`` back into
    the same JSON column. The original ``captures`` list is preserved.

    Returns the number of PyLambda rows touched (idempotent re-runs
    return the same count).
    """

    name: str = "py-scope-resolution"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        conn = store.conn

        # Step 1: gather PyLambda + PyComprehension rows grouped by
        # origin_id. Both kinds carry ``payload['captures']`` (v1.7-#5
        # for lambdas, v1.9-#1 for comprehensions); classification
        # mechanics are identical.
        res = conn.execute(
            """
            MATCH (n:Node)
            WHERE n.source = 'py'
              AND n.kind IN ['PyLambda', 'PyComprehension']
              AND n.payload IS NOT NULL
            RETURN n.id, n.origin_id, n.start_offset, n.end_offset,
                   n.payload, n.kind
            """,
            {},
        )
        # Per origin, separate buckets for lambdas vs comprehensions so
        # we look up the right indexer dict for each.
        per_origin: dict[
            str, list[tuple[str, int, int, str, str]]
        ] = {}
        any_rows = False
        while res.has_next():
            row = res.get_next()
            nid, oid, so, eo, payload, kind = (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
            )
            if oid is None or payload is None:
                continue
            any_rows = True
            per_origin.setdefault(oid, []).append((nid, so, eo, payload, kind))

        if not any_rows:
            return 0

        # Step 2 (v1.9-#3): corpus-wide module-export index. Built once
        # per connector invocation and shared across every consuming
        # file we visit below. Star-imports are not in this map (their
        # exports aren't statically knowable) so captures that resolve
        # through a star-import stay ``unresolved`` — matching the
        # v1.9-#3 out-of-scope rule.
        module_exports = _build_module_exports(conn)
        # v1.10-#1: corpus-wide set of every PyModule.name. Drives the
        # ``module-import`` lift below (only fires for ``import X`` /
        # ``import X.Y`` where X / X.Y is a corpus-resident module).
        corpus_modules = _build_corpus_modules(conn)
        # v1.10-#3: ``{module_qualname: __all__}`` for modules whose
        # source literally declared ``__all__``. Drives the star-import
        # expansion below; absence falls back to the public-name rule.
        module_all_index = _build_module_all_index(conn)

        # Step 3: per-origin, fetch source and build scope index.
        touched = 0
        for origin_id, scope_rows in per_origin.items():
            # v1.9-#3: per consuming file, gather the union of all
            # ``PyImport.aliases`` maps. The cross-file lift below only
            # fires for names that came from an import in THIS file.
            named_imports = _imports_for_origin(conn, origin_id)
            # v1.10-#3: layer star-import expansions on top of explicit
            # named imports. Named bindings win on collision (Python
            # semantics: ``from X import *`` only binds names not
            # already bound). Out-of-corpus star origins contribute
            # nothing, so the captured names stay unresolved.
            star_origins = _star_imports_for_origin(conn, origin_id)
            if star_origins:
                imports_here = _expand_star_imports(
                    star_origins,
                    module_exports,
                    module_all_index,
                    named_imports,
                )
            else:
                imports_here = named_imports
            # v1.10-#2: consuming module's qualname (PyModule.name —
            # package-qualified since v1.11-#1, file stem fallback for
            # top-level files) drives relative-import
            # resolution. Empty string when no PyModule row exists for
            # this origin (defensive); resolver then returns None on
            # any relative target.
            mod_name_res = conn.execute(
                "MATCH (m:Node) WHERE m.source='py' AND m.kind='PyModule' "
                "  AND m.origin_id=$oid RETURN m.name",
                {"oid": origin_id},
            )
            consuming_module = ""
            if mod_name_res.has_next():
                _mname = mod_name_res.get_next()[0]
                if isinstance(_mname, str):
                    consuming_module = _mname
            origin_res = conn.execute(
                "MATCH (o:Origin {id: $oid}) RETURN o.content",
                {"oid": origin_id},
            )
            if not origin_res.has_next():
                continue
            content_str = origin_res.get_next()[0]
            if content_str is None:
                continue
            raw = content_str.encode(BYTES_CODEC)
            try:
                wrapper = MetadataWrapper(cst.parse_module(raw.decode("utf-8")))
                module = wrapper.module
                indexer = _LambdaScopeIndexer(module)
                # v1.10-#3: names imported via ``from X import *`` are
                # module-level bindings in the consuming file but are
                # invisible to ``_bindings_in_block`` (which conservatively
                # treats star-imports as opaque). Inject the star-expansion
                # names into ``module_locals`` BEFORE walking so ``_classify``
                # promotes them to ``module-level``, enabling the cross-file
                # lift below.
                if star_origins:
                    star_only_names = set(imports_here) - set(named_imports)
                    indexer._module_locals.update(star_only_names)
                wrapper.visit(indexer)
            except Exception:
                # Origins that fail to re-parse are skipped; this should
                # only happen on encoding-edge files and is not worth
                # surfacing as a hard error from a connector.
                continue

            for nid, so, eo, payload_str, kind in scope_rows:
                try:
                    payload_obj = json.loads(payload_str)
                except (TypeError, ValueError):
                    continue
                inner = payload_obj.get("payload")
                if not isinstance(inner, dict):
                    continue
                captures = inner.get("captures")
                if not isinstance(captures, list):
                    continue
                if kind == "PyLambda":
                    frame = indexer.lambdas.get((so, eo))
                else:
                    frame = indexer.comprehensions.get((so, eo))
                if frame is None:
                    # Span mismatch — record every capture as unresolved
                    # rather than dropping the row. Defensive: keeps the
                    # payload shape contract honest.
                    resolved = [
                        {"name": str(c), "kind": KIND_UNRESOLVED}
                        for c in captures
                    ]
                else:
                    resolved = []
                    for c in captures:
                        cname = str(c)
                        kind_str = _classify(cname, frame)
                        entry: dict[str, str] = {
                            "name": cname,
                            "kind": kind_str,
                        }
                        # v1.9-#3: any module-level binding that came in
                        # via a PyImport is candidate for the lift. If
                        # the import points at a corpus-resident module
                        # whose export set includes the canonical leaf,
                        # we re-tag to ``cross-file-import`` and attach
                        # ``origin_module``. Otherwise — including when
                        # the origin module isn't in the corpus — the
                        # capture drops to ``unresolved`` so the caller
                        # can tell the difference between "a local def
                        # named foo" and "an imported foo whose home
                        # we couldn't statically locate".
                        if (
                            kind_str == KIND_MODULE_LEVEL
                            and cname in imports_here
                        ):
                            # v1.10-#1: try module-import lift first
                            # (``import X`` shapes). Disjoint from the
                            # v1.9-#3 cross-file lift below.
                            new_kind, origin_mod = _lift_to_module_import(
                                cname,
                                imports_here,
                                corpus_modules,
                                consuming_module,
                            )
                            if new_kind != KIND_MODULE_IMPORT:
                                new_kind, origin_mod = _lift_to_cross_file(
                                    cname,
                                    imports_here,
                                    module_exports,
                                    consuming_module,
                                )
                            entry["kind"] = new_kind
                            if (
                                new_kind
                                in (
                                    KIND_CROSS_FILE_IMPORT,
                                    KIND_MODULE_IMPORT,
                                )
                                and origin_mod is not None
                            ):
                                entry["origin_module"] = origin_mod
                        resolved.append(entry)
                inner["captures_resolved"] = resolved
                new_payload = json.dumps(
                    payload_obj, ensure_ascii=False, sort_keys=True, default=str
                )
                conn.execute(
                    "MATCH (n:Node {id: $id}) SET n.payload = $payload",
                    {"id": nid, "payload": new_payload},
                )
                touched += 1
        return touched


__all__ = ["PyScopeResolutionConnector"]
