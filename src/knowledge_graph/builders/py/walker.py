"""libcst-driven Python walker producing :class:`PyNode` tokens.

Shape mirrors :class:`knowledge_graph.builders.md.lift.MdNode`: a flat
list of dataclasses, each with a byte-precise span and a ``parent_idx``
pointing into the same list. The document node (``PyModule``) is index
0 and parents every top-level statement; nested ``def`` / ``class``
nodes parent through their containing class.

v1 kinds:

* ``PyModule``   — the whole file (offsets 0..len).
* ``PyImport``   — ``import x``, ``import x as y``, ``from p import a, b``.
* ``PyFunction`` — every ``def`` (top-level, nested, method).
* ``PyClass``    — every ``class`` (top-level or nested).

Anything else (``if``, ``for``, ``try``, decorators, async def …) is
deliberately not lifted in v1. The fixture corpus is calibrated for
this scope.

Byte offsets come from libcst's
:class:`libcst.metadata.ByteSpanPositionProvider` — the only metadata
provider that gives raw byte offsets instead of (line, column). The
walker holds onto the source bytes only to slice text for ``name`` and
fallback span recovery; it does not mutate the tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import libcst as cst
from libcst.metadata import ByteSpanPositionProvider, MetadataWrapper


@dataclass(frozen=True)
class PyNode:
    """One lifted Python token.

    ``start`` / ``end`` are inclusive/exclusive byte offsets into the
    file content. ``name`` is the declaration name (function name,
    class name, top-level imported module name); for the module node
    it's the empty string. ``payload`` carries per-kind extras (e.g.
    ``names`` for ``from x import a, b``).
    """

    kind: str
    start: int
    end: int
    name: str
    parent_idx: int | None = None
    payload: dict[str, object] = field(default_factory=dict)


def _import_aliases(node: cst.Import) -> list[str]:
    """Return the dotted module names imported by ``import a, b.c``.

    For ``import a as b`` we record ``a`` — the source module is the
    addressable identifier for name-index matching. Aliases (``b``) can
    be added later if a use-case appears.
    """
    out: list[str] = []
    for alias in node.names:
        out.append(_dotted_name(alias.name))
    return out


def _dotted_name(node: cst.CSTNode) -> str:
    """Flatten ``cst.Attribute``/``cst.Name`` chains to ``a.b.c``."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr.value}"
    return ""


def _from_import_names(node: cst.ImportFrom) -> list[str]:
    """Names imported from a ``from x import a, b`` statement.

    ``from x import *`` returns the literal ``["*"]`` so the writer can
    record the star-import without losing information.
    """
    if isinstance(node.names, cst.ImportStar):
        return ["*"]
    out: list[str] = []
    for alias in node.names:
        if isinstance(alias.name, cst.Name):
            out.append(alias.name.value)
        else:
            out.append(_dotted_name(alias.name))
    return out


def _import_alias_map(node: cst.Import) -> dict[str, str]:
    """Build ``{local_binding: canonical_dotted_name}`` for ``import x[.y][ as z]``.

    Structural-only — preserves the ``asname`` that the bare ``names``
    list drops. ``import a, b.c as q`` → ``{"a": "a", "q": "b.c"}``.
    Consumed by :mod:`knowledge_graph.connectors.py_decorator_semantics`
    (v1.8-#1) to normalise aliased decorator strings before promotion.
    """
    out: dict[str, str] = {}
    for alias in node.names:
        canonical = _dotted_name(alias.name)
        if not canonical:
            continue
        if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
            local = alias.asname.name.value
        else:
            # No `as` — the local binding is the top-level segment
            # (``import a.b.c`` binds ``a``).
            local = canonical.split(".", 1)[0]
        out[local] = canonical
    return out


def _from_import_alias_map(node: cst.ImportFrom) -> dict[str, str]:
    """Build ``{local_binding: canonical_dotted_name}`` for ``from m import a[ as b]``.

    Canonical form uses the source module: ``from dataclasses import
    dataclass as _dc`` → ``{"_dc": "dataclasses.dataclass"}``. Star
    imports return ``{}`` since the bindings are not statically known.
    Relative imports (``from .pkg import x``) record the leading dots
    verbatim so the connector can still recognise pure-local renames
    (``{".pkg.x": ...}``) without resolving the package.
    """
    if isinstance(node.names, cst.ImportStar):
        return {}
    module = _dotted_name(node.module) if node.module is not None else ""
    dots = "." * (node.relative and len(node.relative) or 0)
    prefix = f"{dots}{module}".rstrip(".") if module else dots
    out: dict[str, str] = {}
    for alias in node.names:
        if isinstance(alias.name, cst.Name):
            imported = alias.name.value
        else:
            imported = _dotted_name(alias.name)
        if not imported:
            continue
        canonical = f"{prefix}.{imported}" if prefix else imported
        if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
            local = alias.asname.name.value
        else:
            local = imported.split(".", 1)[0]
        out[local] = canonical
    return out


def _decorator_strings(
    decorators: object, module: cst.Module
) -> list[str]:
    """Render each decorator expression to source text.

    libcst's ``Decorator.decorator`` is a ``BaseExpression`` (Name,
    Attribute, Call, ...). We delegate to ``Module.code_for_node`` so
    parametrised forms like ``@functools.lru_cache(maxsize=8)`` keep
    their argument list intact. Returned list is outer-most first to
    match source order ("the decorator nearest the def runs last").
    """
    out: list[str] = []
    for dec in decorators or ():  # type: ignore[union-attr]
        try:
            text = module.code_for_node(dec.decorator).strip()
        except Exception:
            text = ""
        if text:
            out.append(text)
    return out


class _MatchFinder(cst.CSTVisitor):
    """Collect every ``cst.Match`` node reachable from a subtree.

    Bare ``cst.matchers``-free traversal — we just need the nodes
    themselves so the caller can resolve byte spans through the
    metadata provider. Used to lift PyMatchStatement inside function
    bodies (top-level match is handled directly in the module loop).
    """

    def __init__(self) -> None:
        super().__init__()
        self.matches: list[cst.Match] = []

    def visit_Match(self, node: cst.Match) -> None:
        self.matches.append(node)


def _find_match_statements(subtree: cst.CSTNode) -> list[cst.Match]:
    finder = _MatchFinder()
    subtree.visit(finder)
    return finder.matches


# v1.7-#3: per-arm classification for PyMatchStatement.
#
# Closed pattern_kind set (chosen once, see JOURNAL v1.7-#3 retro):
#   literal | name | class | or | wildcard | sequence | mapping
#
# Mapping from libcst pattern node to pattern_kind:
#   MatchValue, MatchSingleton          -> literal
#   MatchOr                              -> or
#   MatchClass                           -> class
#   MatchList, MatchTuple                -> sequence
#   MatchMapping                         -> mapping
#   MatchAs(pattern=None, name=None)     -> wildcard  (the ``_`` case)
#   MatchAs(pattern=None, name=Name)     -> name      (capture-only)
#   MatchAs(pattern=X,    name=Name?)    -> classify X (and add ``as`` name)
#   MatchStar                            -> name (capture inside a sequence)
def _pattern_kind(pat: cst.BaseMatchPattern) -> str:
    if isinstance(pat, cst.MatchAs):
        if pat.pattern is None:
            return "wildcard" if pat.name is None else "name"
        return _pattern_kind(pat.pattern)
    if isinstance(pat, (cst.MatchValue, cst.MatchSingleton)):
        return "literal"
    if isinstance(pat, cst.MatchOr):
        return "or"
    if isinstance(pat, cst.MatchClass):
        return "class"
    if isinstance(pat, (cst.MatchList, cst.MatchTuple)):
        return "sequence"
    if isinstance(pat, cst.MatchMapping):
        return "mapping"
    if isinstance(pat, cst.MatchStar):
        return "name"
    return "wildcard"


def _collect_bound_names(pat: cst.BaseMatchPattern, out: list[str]) -> None:
    """Collect names this pattern binds, in source order, deduped.

    Walks all binding sites: ``MatchAs.name``, ``MatchStar.name``,
    ``MatchClass`` positional + keyword sub-patterns, ``MatchMapping``
    values + ``rest``, ``MatchList``/``MatchTuple`` sequence elements,
    and ``MatchOr`` alternatives (PEP 634 requires all OR-alternatives
    bind the same names; collecting from one alternative is enough,
    but we walk all and dedupe to stay robust).
    """
    if isinstance(pat, cst.MatchAs):
        if pat.name is not None and pat.name.value not in out:
            out.append(pat.name.value)
        if pat.pattern is not None:
            _collect_bound_names(pat.pattern, out)
        return
    if isinstance(pat, cst.MatchStar):
        if pat.name is not None and pat.name.value not in out:
            out.append(pat.name.value)
        return
    if isinstance(pat, (cst.MatchList, cst.MatchTuple)):
        for el in pat.patterns:
            if isinstance(el, cst.MatchSequenceElement):
                _collect_bound_names(el.value, out)
            elif isinstance(el, cst.MatchStar):
                _collect_bound_names(el, out)
        return
    if isinstance(pat, cst.MatchMapping):
        for el in pat.elements:
            _collect_bound_names(el.pattern, out)
        if pat.rest is not None and pat.rest.value not in out:
            out.append(pat.rest.value)
        return
    if isinstance(pat, cst.MatchClass):
        for el in pat.patterns:
            if isinstance(el, cst.MatchSequenceElement):
                _collect_bound_names(el.value, out)
        for kw in pat.kwds:
            _collect_bound_names(kw.pattern, out)
        return
    if isinstance(pat, cst.MatchOr):
        for alt in pat.patterns:
            _collect_bound_names(alt, out)
        return
    # MatchValue / MatchSingleton bind no names.
    return


def _match_arms_payload(match_node: cst.Match) -> list[dict[str, object]]:
    """Build the ``arms`` payload list for one ``cst.Match`` node."""
    arms: list[dict[str, object]] = []
    for case in match_node.cases:
        bound: list[str] = []
        _collect_bound_names(case.pattern, bound)
        arms.append(
            {
                "pattern_kind": _pattern_kind(case.pattern),
                "bound_names": bound,
                "has_guard": case.guard is not None,
            }
        )
    return arms


class _WalrusFinder(cst.CSTVisitor):
    """Set ``self.found = True`` if any ``cst.NamedExpr`` appears."""

    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_NamedExpr(self, node: cst.NamedExpr) -> None:  # noqa: ARG002
        self.found = True


def _has_walrus(subtree: cst.CSTNode) -> bool:
    f = _WalrusFinder()
    subtree.visit(f)
    return f.found


_COMP_FORM_BY_TYPE: dict[type, str] = {
    cst.ListComp: "list",
    cst.SetComp: "set",
    cst.DictComp: "dict",
    cst.GeneratorExp: "generator",
}


class _ScopedComprehensionFinder(cst.CSTVisitor):
    """Collect (comp_node, form, parent_cst) honouring lexical scopes.

    Maintains a stack whose top is the nearest enclosing scope-creating
    CST node: the Module (sentinel), any FunctionDef / ClassDef, or any
    comprehension on the way down. Each comprehension records its parent
    as that current top-of-stack so consumers can reattach parent_idx to
    the surrounding function / class / outer comp rather than to the
    module wholesale.

    The visitor traverses the *entire* module in one pass; recording is
    cheap and avoids re-walking subtrees once per scope.
    """

    def __init__(self, module: cst.Module) -> None:
        super().__init__()
        self._stack: list[cst.CSTNode] = [module]
        self.found: list[tuple[cst.CSTNode, str, cst.CSTNode]] = []

    def _push(self, node: cst.CSTNode) -> None:
        self._stack.append(node)

    def _pop(self, node: cst.CSTNode) -> None:  # noqa: ARG002
        self._stack.pop()

    def _record(self, node: cst.CSTNode) -> None:
        form = _COMP_FORM_BY_TYPE.get(type(node))
        if form is not None:
            self.found.append((node, form, self._stack[-1]))

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._push(node)

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self._pop(original_node)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._push(node)

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self._pop(original_node)

    def visit_ListComp(self, node: cst.ListComp) -> None:
        self._record(node)
        self._push(node)

    def leave_ListComp(self, original_node: cst.ListComp) -> None:
        self._pop(original_node)

    def visit_SetComp(self, node: cst.SetComp) -> None:
        self._record(node)
        self._push(node)

    def leave_SetComp(self, original_node: cst.SetComp) -> None:
        self._pop(original_node)

    def visit_DictComp(self, node: cst.DictComp) -> None:
        self._record(node)
        self._push(node)

    def leave_DictComp(self, original_node: cst.DictComp) -> None:
        self._pop(original_node)

    def visit_GeneratorExp(self, node: cst.GeneratorExp) -> None:
        self._record(node)
        self._push(node)

    def leave_GeneratorExp(self, original_node: cst.GeneratorExp) -> None:
        self._pop(original_node)


def _find_comprehensions_scoped(
    module: cst.Module,
) -> list[tuple[cst.CSTNode, str, cst.CSTNode]]:
    f = _ScopedComprehensionFinder(module)
    module.visit(f)
    return f.found


# v1.7-#5: lambda capture analysis.
#
# A lambda's "captures" = Name identifiers loaded inside its body that
# are NOT parameters of the lambda itself. We deliberately do NOT verify
# those names resolve in any enclosing lexical scope — that's static-
# analysis territory queued for v1.8+. The heuristic suffices for
# graph-level "this lambda references symbol X" queries.
#
# Skipped during the body walk:
#   * ``Attribute.attr`` — only the receiver Name counts (``self.attr``
#     contributes ``self``, never ``attr``).
#   * ``Arg.keyword`` — keyword argument names (``foo(x=1)``) are not
#     name loads.
#   * Nested ``Lambda`` subtrees — each nested lambda is emitted in its
#     own right; its parameters mask names that would otherwise leak
#     into the outer lambda's capture set.
def _lambda_param_names(params: cst.Parameters) -> set[str]:
    """All identifiers bound by a lambda's parameter list."""
    names: set[str] = set()
    for p in list(params.posonly_params) + list(params.params) + list(
        params.kwonly_params
    ):
        names.add(p.name.value)
    if isinstance(params.star_arg, cst.Param):
        names.add(params.star_arg.name.value)
    if params.star_kwarg is not None:
        names.add(params.star_kwarg.name.value)
    return names


def _collect_load_names(node: cst.CSTNode, out: set[str]) -> None:
    """Recursive walk collecting Name loads inside a lambda body.

    Honours the skip rules documented above: attribute ``.attr`` Names,
    keyword-argument keyword Names, and nested Lambda subtrees are not
    descended into.
    """
    if isinstance(node, cst.Name):
        out.add(node.value)
        return
    if isinstance(node, cst.Attribute):
        _collect_load_names(node.value, out)
        return
    if isinstance(node, cst.Arg):
        _collect_load_names(node.value, out)
        return
    if isinstance(node, cst.Lambda):
        # Nested lambdas are visited independently; do not bleed their
        # body name references into the outer lambda's capture set.
        return
    for child in node.children:
        _collect_load_names(child, out)


class _ScopedLambdaFinder(cst.CSTVisitor):
    """Collect ``(lambda_node, parent_cst)`` honouring lexical scopes.

    Mirrors :class:`_ScopedComprehensionFinder`. The stack top is the
    nearest enclosing scope-creating CST node (Module / FunctionDef /
    ClassDef / outer Lambda / Comprehension). Comprehensions count as
    scopes too so that a lambda nested inside a comprehension parents at
    the comprehension, not the function around it.
    """

    def __init__(self, module: cst.Module) -> None:
        super().__init__()
        self._stack: list[cst.CSTNode] = [module]
        self.found: list[tuple[cst.Lambda, cst.CSTNode]] = []

    def _push(self, node: cst.CSTNode) -> None:
        self._stack.append(node)

    def _pop(self, node: cst.CSTNode) -> None:  # noqa: ARG002
        self._stack.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._push(node)

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self._pop(original_node)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._push(node)

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self._pop(original_node)

    def visit_ListComp(self, node: cst.ListComp) -> None:
        self._push(node)

    def leave_ListComp(self, original_node: cst.ListComp) -> None:
        self._pop(original_node)

    def visit_SetComp(self, node: cst.SetComp) -> None:
        self._push(node)

    def leave_SetComp(self, original_node: cst.SetComp) -> None:
        self._pop(original_node)

    def visit_DictComp(self, node: cst.DictComp) -> None:
        self._push(node)

    def leave_DictComp(self, original_node: cst.DictComp) -> None:
        self._pop(original_node)

    def visit_GeneratorExp(self, node: cst.GeneratorExp) -> None:
        self._push(node)

    def leave_GeneratorExp(self, original_node: cst.GeneratorExp) -> None:
        self._pop(original_node)

    def visit_Lambda(self, node: cst.Lambda) -> None:
        self.found.append((node, self._stack[-1]))
        self._push(node)

    def leave_Lambda(self, original_node: cst.Lambda) -> None:
        self._pop(original_node)


def _find_lambdas_scoped(
    module: cst.Module,
) -> list[tuple[cst.Lambda, cst.CSTNode]]:
    f = _ScopedLambdaFinder(module)
    module.visit(f)
    return f.found


def _extract_dunder_all(module: cst.Module) -> list[str] | None:
    """Return the literal ``__all__`` list at module scope, if present.

    Only the literal-list / literal-tuple form is recognised — dynamic
    constructions (``__all__ = list(...)``, augmented assignment) are
    out of scope for v1.6 and would return ``None`` here.
    """
    for stmt in module.body:
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for small in stmt.body:
            if not isinstance(small, cst.Assign):
                continue
            if len(small.targets) != 1:
                continue
            target = small.targets[0].target
            if not (isinstance(target, cst.Name) and target.value == "__all__"):
                continue
            value = small.value
            if not isinstance(value, (cst.List, cst.Tuple)):
                return None
            out: list[str] = []
            for el in value.elements:
                if isinstance(el, cst.Element) and isinstance(
                    el.value, cst.SimpleString
                ):
                    out.append(el.value.evaluated_value)
            return out
    return None


def lift_python(content: bytes) -> list[PyNode]:
    """Lift ``content`` (Python source bytes) into a flat PyNode list.

    Returns at minimum a single ``PyModule`` node when the source
    parses but contains no top-level def/class/import. Raises whatever
    libcst raises on a parse error — callers are expected to handle
    that as a hard failure (the SV builder does the same with pyslang).
    """
    text = content.decode("utf-8")
    wrapper = MetadataWrapper(cst.parse_module(text))
    spans = wrapper.resolve(ByteSpanPositionProvider)
    module = wrapper.module

    nodes: list[PyNode] = []
    # Map CST node identity -> index in ``nodes``. Populated as we
    # emit PyModule / PyFunction / PyClass / PyComprehension so that
    # the scoped comprehension pass can resolve parent_idx by looking
    # up its CST-level parent (nearest enclosing function / class /
    # outer comprehension / module).
    cst_to_idx: dict[int, int] = {}
    module_payload: dict[str, object] = {}
    all_exports = _extract_dunder_all(module)
    if all_exports is not None:
        module_payload["all_exports"] = all_exports
    # Index 0 is always the module node, covering the whole file.
    nodes.append(
        PyNode(
            kind="PyModule",
            start=0,
            end=len(content),
            name="",
            parent_idx=None,
            payload=module_payload,
        )
    )
    cst_to_idx[id(module)] = 0

    def _emit_def_or_class(node: cst.CSTNode, parent_idx: int) -> None:
        """Recursive walk for FunctionDef / ClassDef bodies."""
        sp = spans.get(node)
        if sp is None:
            return
        payload: dict[str, object] = {}
        if isinstance(node, cst.FunctionDef):
            kind = "PyFunction"
            name = node.name.value
            decs = _decorator_strings(node.decorators, module)
            if decs:
                payload["decorators"] = decs
            payload["is_async"] = node.asynchronous is not None
            payload["has_walrus"] = _has_walrus(node.body)
        elif isinstance(node, cst.ClassDef):
            kind = "PyClass"
            name = node.name.value
            decs = _decorator_strings(node.decorators, module)
            if decs:
                payload["decorators"] = decs
        else:
            return
        nodes.append(
            PyNode(
                kind=kind,
                start=sp.start,
                end=sp.start + sp.length,
                name=name,
                parent_idx=parent_idx,
                payload=payload,
            )
        )
        this_idx = len(nodes) - 1
        cst_to_idx[id(node)] = this_idx
        # Function bodies may contain `match` statements at any depth.
        # Lift each as PyMatchStatement parented under this def/class.
        if isinstance(node, cst.FunctionDef):
            for match_node in _find_match_statements(node.body):
                msp = spans.get(match_node)
                if msp is None:
                    continue
                nodes.append(
                    PyNode(
                        kind="PyMatchStatement",
                        start=msp.start,
                        end=msp.start + msp.length,
                        name="",
                        parent_idx=this_idx,
                        payload={"arms": _match_arms_payload(match_node)},
                    )
                )
        # Recurse into the body looking for nested def/class. Imports
        # nested inside a function are NOT lifted in v1 (charter scope).
        for child in node.body.body:
            inner = child
            if isinstance(child, cst.SimpleStatementLine):
                continue  # nested simple statements (assigns, imports) skipped
            if isinstance(inner, (cst.FunctionDef, cst.ClassDef)):
                _emit_def_or_class(inner, this_idx)

    def _emit_simple_stmt(
        stmt: cst.SimpleStatementLine,
        *,
        runtime: bool,
        import_guard: str | None = None,
    ) -> None:
        """Emit PyImport / PyTypeAlias for each small statement in ``stmt``.

        ``runtime=False`` is used for the body of an ``if TYPE_CHECKING:``
        block — imports there are only valid for type-checkers and must
        not be issued at runtime.

        ``import_guard`` (v1.8-#2) records the wrapping control-flow
        construct from the closed set
        ``{"type-checking", "try-import", "version-guard",
        "conditional", None}``. Only attached to PyImport rows (not
        PyTypeAlias). Absent payload key == ``None``.
        """
        for small in stmt.body:
            if isinstance(small, cst.TypeAlias):
                sp = spans.get(stmt)
                if sp is None:
                    continue
                nodes.append(
                    PyNode(
                        kind="PyTypeAlias",
                        start=sp.start,
                        end=sp.start + sp.length,
                        name=small.name.value,
                        parent_idx=0,
                        payload={},
                    )
                )
                continue
            if isinstance(small, (cst.Import, cst.ImportFrom)):
                sp = spans.get(stmt)
                if sp is None:
                    continue
                if isinstance(small, cst.Import):
                    names = _import_aliases(small)
                    primary = names[0] if names else ""
                    payload: dict[str, object] = {
                        "names": names,
                        "aliases": _import_alias_map(small),
                        "kind": "import",
                        "runtime": runtime,
                    }
                else:
                    names = _from_import_names(small)
                    module_name = (
                        _dotted_name(small.module)
                        if small.module is not None
                        else ""
                    )
                    primary = module_name
                    payload = {
                        "names": names,
                        "aliases": _from_import_alias_map(small),
                        "module": module_name,
                        "kind": "from",
                        "level": small.relative and len(small.relative) or 0,
                        "runtime": runtime,
                    }
                if import_guard is not None:
                    payload["import_guard"] = import_guard
                nodes.append(
                    PyNode(
                        kind="PyImport",
                        start=sp.start,
                        end=sp.start + sp.length,
                        name=primary,
                        parent_idx=0,
                        payload=payload,
                    )
                )

    def _is_type_checking_test(expr: cst.BaseExpression) -> bool:
        """Recognise ``TYPE_CHECKING`` and ``typing.TYPE_CHECKING`` tests."""
        if isinstance(expr, cst.Name) and expr.value == "TYPE_CHECKING":
            return True
        if isinstance(expr, cst.Attribute) and expr.attr.value == "TYPE_CHECKING":
            return True
        return False

    def _is_version_info_test(expr: cst.BaseExpression) -> bool:
        """Recognise ``sys.version_info ...`` comparisons.

        Matches any Compare whose left operand is an Attribute chain
        ending in ``version_info`` (covers ``sys.version_info``,
        ``_sys.version_info``, ``compat.sys.version_info``).
        """
        if not isinstance(expr, cst.Comparison):
            return False
        left = expr.left
        if isinstance(left, cst.Attribute) and left.attr.value == "version_info":
            return True
        return False

    def _try_block_imports_only(node: cst.Try) -> bool:
        """True if the ``try`` body's small statements are all imports.

        Used to recognise the optional-import idiom; ``try: import X /
        except ImportError: ...``. We don't require the except handler
        catches ``ImportError`` literally — any try-wrapped import is
        guarded against import failure in practice.
        """
        for inner in node.body.body:
            if isinstance(inner, cst.SimpleStatementLine):
                for small in inner.body:
                    if not isinstance(small, (cst.Import, cst.ImportFrom)):
                        return False
            else:
                # nested def/class/etc inside try — not the simple idiom
                return False
        return True

    def _emit_if_branch_imports(
        branch_body: cst.IndentedBlock, *, runtime: bool, import_guard: str
    ) -> None:
        for inner in branch_body.body:
            if isinstance(inner, cst.SimpleStatementLine):
                _emit_simple_stmt(
                    inner, runtime=runtime, import_guard=import_guard
                )

    for stmt in module.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            _emit_simple_stmt(stmt, runtime=True)
        elif isinstance(stmt, (cst.FunctionDef, cst.ClassDef)):
            _emit_def_or_class(stmt, 0)
        elif isinstance(stmt, cst.Match):
            msp = spans.get(stmt)
            if msp is not None:
                nodes.append(
                    PyNode(
                        kind="PyMatchStatement",
                        start=msp.start,
                        end=msp.start + msp.length,
                        name="",
                        parent_idx=0,
                        payload={"arms": _match_arms_payload(stmt)},
                    )
                )
        elif isinstance(stmt, cst.If):
            # v1.8-#2: closed-set import_guard dispatch.
            if _is_type_checking_test(stmt.test):
                # Imports under ``if TYPE_CHECKING:`` are runtime=False.
                for inner in stmt.body.body:
                    if isinstance(inner, cst.SimpleStatementLine):
                        _emit_simple_stmt(
                            inner, runtime=False, import_guard="type-checking"
                        )
            elif _is_version_info_test(stmt.test):
                _emit_if_branch_imports(
                    stmt.body, runtime=True, import_guard="version-guard"
                )
                # `else` / `elif` branches of a version guard are still
                # version-guarded.
                orelse = stmt.orelse
                while orelse is not None:
                    if isinstance(orelse, cst.If):
                        _emit_if_branch_imports(
                            orelse.body,
                            runtime=True,
                            import_guard="version-guard",
                        )
                        orelse = orelse.orelse
                    elif isinstance(orelse, cst.Else):
                        _emit_if_branch_imports(
                            orelse.body,
                            runtime=True,
                            import_guard="version-guard",
                        )
                        orelse = None
                    else:
                        orelse = None
            else:
                _emit_if_branch_imports(
                    stmt.body, runtime=True, import_guard="conditional"
                )
                orelse = stmt.orelse
                while orelse is not None:
                    if isinstance(orelse, cst.If):
                        _emit_if_branch_imports(
                            orelse.body,
                            runtime=True,
                            import_guard="conditional",
                        )
                        orelse = orelse.orelse
                    elif isinstance(orelse, cst.Else):
                        _emit_if_branch_imports(
                            orelse.body,
                            runtime=True,
                            import_guard="conditional",
                        )
                        orelse = None
                    else:
                        orelse = None
        elif isinstance(stmt, cst.Try) and _try_block_imports_only(stmt):
            # ``try: import X / except ImportError: import Y`` — both
            # branches recorded as guarded imports.
            for inner in stmt.body.body:
                if isinstance(inner, cst.SimpleStatementLine):
                    _emit_simple_stmt(
                        inner, runtime=True, import_guard="try-import"
                    )
            for handler in stmt.handlers:
                for inner in handler.body.body:
                    if isinstance(inner, cst.SimpleStatementLine):
                        # Only emit if the handler statements are also
                        # imports (the fallback form); other small
                        # statements (re-raise, logging) are not lifted.
                        if any(
                            isinstance(s, (cst.Import, cst.ImportFrom))
                            for s in inner.body
                        ):
                            _emit_simple_stmt(
                                inner,
                                runtime=True,
                                import_guard="try-import",
                            )
        # Anything else (For, while, with, ...) is intentionally skipped
        # in v1.

    # Scope-aware comprehension sweep (v1.7-#2). Each PyComprehension
    # attaches to its nearest enclosing scope-creating CST node:
    # PyFunction / PyClass / outer PyComprehension, or PyModule when
    # the comprehension is at module top level. Walk source order so
    # outer comps land in ``cst_to_idx`` before their inner peers ask
    # for them.
    scoped = _find_comprehensions_scoped(module)
    scoped.sort(
        key=lambda triple: (
            (spans.get(triple[0]).start if spans.get(triple[0]) else 0),
            -(spans.get(triple[0]).length if spans.get(triple[0]) else 0),
        )
    )
    for comp_node, form, parent_cst in scoped:
        csp = spans.get(comp_node)
        if csp is None:
            continue
        # Resolve parent: nearest enclosing emitted node. If the
        # CST-level parent is a scope we didn't emit (e.g. a class
        # body that we DID emit, or a nested comp we just emitted),
        # the map already has it; otherwise fall back to PyModule.
        parent_idx = cst_to_idx.get(id(parent_cst), 0)
        nodes.append(
            PyNode(
                kind="PyComprehension",
                start=csp.start,
                end=csp.start + csp.length,
                name="",
                parent_idx=parent_idx,
                payload={"form": form},
            )
        )
        cst_to_idx[id(comp_node)] = len(nodes) - 1

    # Scope-aware lambda sweep (v1.7-#5). Parents to nearest enclosing
    # scope using the same cst_to_idx map. Outer-first ordering ensures
    # nested lambdas can look up their parent PyLambda by id.
    scoped_lambdas = _find_lambdas_scoped(module)
    scoped_lambdas.sort(
        key=lambda pair: (
            (spans.get(pair[0]).start if spans.get(pair[0]) else 0),
            -(spans.get(pair[0]).length if spans.get(pair[0]) else 0),
        )
    )
    for lam_node, parent_cst in scoped_lambdas:
        lsp = spans.get(lam_node)
        if lsp is None:
            continue
        loaded: set[str] = set()
        _collect_load_names(lam_node.body, loaded)
        params = _lambda_param_names(lam_node.params)
        captures = sorted(loaded - params)
        parent_idx = cst_to_idx.get(id(parent_cst), 0)
        nodes.append(
            PyNode(
                kind="PyLambda",
                start=lsp.start,
                end=lsp.start + lsp.length,
                name="",
                parent_idx=parent_idx,
                payload={"captures": captures},
            )
        )
        cst_to_idx[id(lam_node)] = len(nodes) - 1

    return nodes


__all__ = ["PyNode", "lift_python"]
