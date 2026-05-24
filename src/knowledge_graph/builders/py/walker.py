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
                        payload={},
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
        stmt: cst.SimpleStatementLine, *, runtime: bool
    ) -> None:
        """Emit PyImport / PyTypeAlias for each small statement in ``stmt``.

        ``runtime=False`` is used for the body of an ``if TYPE_CHECKING:``
        block — imports there are only valid for type-checkers and must
        not be issued at runtime.
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
                        "module": module_name,
                        "kind": "from",
                        "level": small.relative and len(small.relative) or 0,
                        "runtime": runtime,
                    }
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
                        payload={},
                    )
                )
        elif isinstance(stmt, cst.If) and _is_type_checking_test(stmt.test):
            # Imports under ``if TYPE_CHECKING:`` are runtime=False.
            for inner in stmt.body.body:
                if isinstance(inner, cst.SimpleStatementLine):
                    _emit_simple_stmt(inner, runtime=False)
        # Anything else (other If, For, Try, ...) is intentionally skipped
        # in v1.

    return nodes


__all__ = ["PyNode", "lift_python"]
