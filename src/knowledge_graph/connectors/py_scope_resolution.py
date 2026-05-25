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
   the closed set::

       {"local-in-enclosing", "module-level", "builtin", "unresolved"}

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


# Closed classification set.
KIND_LOCAL_ENCLOSING = "local-in-enclosing"
KIND_MODULE_LEVEL = "module-level"
KIND_BUILTIN = "builtin"
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

        # Step 2: per-origin, fetch source and build scope index.
        touched = 0
        for origin_id, scope_rows in per_origin.items():
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
                    resolved = [
                        {"name": str(c), "kind": _classify(str(c), frame)}
                        for c in captures
                    ]
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
