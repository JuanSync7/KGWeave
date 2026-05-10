# @summary
# V2 dataflow walker — Wave 1 / track A (walker core).
# Recursive elaborated-AST visitor over pyslang ExpressionSyntax nodes that
# emits Operator / Literal / Index entities (layer="ast") plus operand/slice
# edges. Stable IDs derived from a path-hash of (child_index, syntax_kind)
# pairs from the process root. Track A only — statements/cross-refs land on
# parallel tracks (B/C).
# Exports: V2DataflowWalker, V2_WALKER_SOURCE
# Deps: pyslang (hard), kgweave.knowledge_graph.common
# @end-summary
"""V2 dataflow walker — elaborated-AST mirror, expression layer.

This is the **track A** slice of Wave 1: only operator / literal / index node
emission, with structural ``operand`` / ``slice_of`` / ``slice_msb`` /
``slice_lsb`` edges. Statement decomposition (IfStatement, Branch, Loop,
Assignment) and cross-reference edges (``references`` to declared
Signal/Port) are tracks B and C and arrive separately.

Per ``docs/v2_dataflow_schema.md``:

* every emitted Entity carries ``layer="ast"``;
* every emitted Triple carries ``layer="ast"``;
* Literal nodes are **shared by value within a module** (one ``m.lit.32h0``
  per module, regardless of use-site count);
* internal node IDs use ``<module>.<process_kind>_<idx>.<path_hash>`` where
  ``<path_hash>`` is the first 8 hex chars of sha1 over the
  ``(child_index, syntax_kind)`` path from the process root to the node.

The walker re-uses v1's process-discovery logic (continuous assigns +
``always_*`` blocks in source order) so process indices match v1 IDs and
queries can pivot between v1 (``Process(...)`` → ``drives_signal``) and v2
(``Process(...)`` → AST internals) on the same node.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import pyslang as _ps  # noqa: E402 — hard dep

from kgweave.knowledge_graph.common import Entity, ExtractionResult, Triple


__all__ = ["V2DataflowWalker", "V2_WALKER_SOURCE"]

logger = logging.getLogger("kgweave.knowledge_graph.extraction.sv_v2_walker")

V2_WALKER_SOURCE = "sv_v2_walker"
_AST_LAYER = "ast"


# ---------------------------------------------------------------------------
# Pyslang helpers (mirror v1 conventions in sv_dataflow_extractor.py)
# ---------------------------------------------------------------------------


def _kind_str(node: Any) -> str:
    k = getattr(node, "kind", None)
    return str(k) if k is not None else ""


def _kind_local(node: Any) -> str:
    """Return the local syntax-kind name (``"AddExpression"``) without prefix."""
    k = _kind_str(node)
    if "." in k:
        return k.rsplit(".", 1)[-1]
    return k


def _iter_children(node: Any) -> Iterator[Any]:
    try:
        for c in node:
            yield c
    except TypeError:
        return


def _list_children(node: Any) -> List[Any]:
    return list(_iter_children(node))


def _token_text(tok: Any) -> Optional[str]:
    if tok is None:
        return None
    text = getattr(tok, "valueText", None)
    if text is None:
        if isinstance(tok, str):
            return tok.strip() or None
        return None
    text = text.strip()
    return text or None


def _is_token(node: Any) -> bool:
    """True if *node* is a leaf token rather than a syntax node."""
    return _kind_str(node).startswith("TokenKind.")


def _is_skip_kind(node: Any) -> bool:
    """Nodes the walker never emits or treats as operands.

    Per schema doc § 'What gets skipped': leaf tokens, list wrappers, and
    pure-grammar containers (parens, ``begin``/``end``, commas, semicolons)
    carry no semantic content. Note that the recursive walker still
    *descends through* list wrappers — it just won't emit a node for them
    or count them as operands. ``_is_token`` distinguishes the leaf case.
    """
    k = _kind_str(node)
    if k.startswith("TokenKind."):
        return True
    if k.endswith("SyntaxList") or k.endswith("SeparatedList") or k.endswith("TokenList"):
        return True
    return False


# ---------------------------------------------------------------------------
# Module / process discovery (mirrors v1 walker for ID-stability)
# ---------------------------------------------------------------------------


def _find_top_level_modules(root: Any) -> List[Any]:
    found: List[Any] = []

    def walk(node: Any) -> None:
        if "ModuleDeclaration" in _kind_str(node):
            found.append(node)
            return
        for c in _iter_children(node):
            walk(c)

    walk(root)
    return found


def _module_name(decl: Any) -> Optional[str]:
    for c in _iter_children(decl):
        if "ModuleHeader" in _kind_str(c):
            return _token_text(getattr(c, "name", None))
    return None


_ALWAYS_KIND_TO_LABEL = {
    "AlwaysFFBlock": "always_ff",
    "AlwaysCombBlock": "always_comb",
    "AlwaysLatchBlock": "always_latch",
    "AlwaysBlock": "always",
}


def _collect_process_nodes(mod_decl: Any) -> List[Tuple[str, Any]]:
    """[(kind_label, node)] in source order — same logic as v1."""
    results: List[Tuple[str, Any]] = []

    def walk(node: Any) -> None:
        k = _kind_str(node)
        if "ModuleDeclaration" in k and node is not mod_decl:
            return
        if k.endswith("ContinuousAssign"):
            results.append(("assign", node))
            return
        for label_suffix, label in _ALWAYS_KIND_TO_LABEL.items():
            if k.endswith(label_suffix):
                results.append((label, node))
                return
        for c in _iter_children(node):
            walk(c)

    walk(mod_decl)
    return results


# ---------------------------------------------------------------------------
# Operator / Literal / Index classification
# ---------------------------------------------------------------------------

# Suffixes (the local kind name *ends* with these). Anything matching is an
# operator expression with ordered operand children (sub-expression nodes).
_OPERATOR_SUFFIXES: Tuple[str, ...] = (
    # arithmetic
    "AddExpression", "SubtractExpression", "MultiplyExpression", "DivideExpression",
    "ModExpression", "PowerExpression",
    # comparison
    "EqualityExpression", "InequalityExpression",
    "CaseEqualityExpression", "CaseInequalityExpression",
    "WildcardEqualityExpression", "WildcardInequalityExpression",
    "LessThanExpression", "LessThanEqualExpression",
    "GreaterThanExpression", "GreaterThanEqualExpression",
    # logical
    "LogicalAndExpression", "LogicalOrExpression",
    "LogicalImplicationExpression", "LogicalEquivalenceExpression",
    # bitwise
    "BinaryAndExpression", "BinaryOrExpression",
    "BinaryXorExpression", "BinaryXnorExpression",
    # shifts
    "LogicalShiftLeftExpression", "LogicalShiftRightExpression",
    "ArithmeticShiftLeftExpression", "ArithmeticShiftRightExpression",
    # unary
    "UnaryPlusExpression", "UnaryMinusExpression",
    "UnaryBitwiseNotExpression", "UnaryLogicalNotExpression",
    "UnaryBitwiseAndExpression", "UnaryBitwiseOrExpression",
    "UnaryBitwiseXorExpression", "UnaryBitwiseNandExpression",
    "UnaryBitwiseNorExpression", "UnaryBitwiseXnorExpression",
    "UnaryPreincrementExpression", "UnaryPredecrementExpression",
    "UnaryPostincrementExpression", "UnaryPostdecrementExpression",
    # ternary
    "ConditionalExpression",
    # concatenation / replication
    "ConcatenationExpression", "MultipleConcatenationExpression",
)

_LITERAL_KINDS: Tuple[str, ...] = (
    "IntegerLiteralExpression",
    "IntegerVectorExpression",
    "RealLiteralExpression",
    "TimeLiteralExpression",
    "StringLiteralExpression",
    "UnbasedUnsizedLiteralExpression",
    "NullLiteralExpression",
    "DefaultPatternKeyExpression",
)


def _is_operator(node: Any) -> bool:
    name = _kind_local(node)
    return any(name.endswith(s) for s in _OPERATOR_SUFFIXES)


def _operator_kind(node: Any) -> str:
    """Return the canonical operator kind (e.g. ``"Add"``, ``"LogicalAnd"``).

    Strips the ``Expression`` suffix so queries can use simple names.
    """
    name = _kind_local(node)
    if name.endswith("Expression"):
        return name[: -len("Expression")]
    return name


def _is_literal(node: Any) -> bool:
    return _kind_local(node) in _LITERAL_KINDS


def _literal_text(node: Any) -> str:
    """Stringify a literal node's source tokens.

    Stable across reformatting because we concatenate token ``valueText`` —
    no whitespace, no comments. Used for both display and module-level
    de-duplication keys.
    """
    parts: List[str] = []
    for child in _iter_children(node):
        if _is_token(child):
            txt = _token_text(child)
            if txt is not None:
                parts.append(txt)
        else:
            # Recurse — some literals nest (e.g. SizedLiteralExpression).
            parts.append(_literal_text(child))
    return "".join(parts)


def _normalise_literal_token(text: str) -> str:
    """Canonicalise a literal's text for use in a stable node ID.

    Strips characters that are illegal in our ``.``-separated naming scheme
    (apostrophe in ``32'h1F`` → ``32h1F``, spaces collapsed, etc.).
    """
    out = []
    for ch in text:
        if ch.isalnum() or ch in "_-":
            out.append(ch)
        # everything else (', ", whitespace, $, etc.) is dropped
    return "".join(out) or "lit"


# ---------------------------------------------------------------------------
# Bit-slice / index detection
# ---------------------------------------------------------------------------


def _identifier_select_base(node: Any) -> Optional[str]:
    """Return the base identifier text under an ``IdentifierSelectName`` node.

    The first ``Identifier`` token is the base signal; subsequent
    ``ElementSelect`` children carry the slice.
    """
    if not _kind_local(node).endswith("IdentifierSelectName"):
        return None
    for child in _iter_children(node):
        if _kind_str(child).endswith("Identifier") and not _kind_str(child).endswith("Name"):
            return _token_text(child)
    return None


def _identifier_select_selector(node: Any) -> Optional[Any]:
    """First ``ElementSelect`` descendant of an IdentifierSelectName.

    pyslang nests the selectors under a ``SyntaxList`` wrapper, so we
    descend through list-kind containers.
    """
    def find(n: Any) -> Optional[Any]:
        for child in _iter_children(n):
            k = _kind_local(child)
            if k.endswith("ElementSelect"):
                return child
            if _kind_str(child).endswith("SyntaxList") or _kind_str(child).endswith("SeparatedList"):
                r = find(child)
                if r is not None:
                    return r
        return None
    return find(node)


def _slice_bounds(elem_select: Any) -> Optional[Tuple[Any, Any]]:
    """Return (msb_expr, lsb_expr) for an ``ElementSelect`` child node.

    For ``a[3:0]`` returns (IntegerLiteral(3), IntegerLiteral(0)).
    For a single-bit ``a[i]`` returns (i, i) — caller decides whether to
    emit two distinct lit edges or just one.
    Returns ``None`` if the selector shape is not understood.
    """
    # ElementSelect → [ <inner> ]   inner is one of:
    #   SimpleRangeSelect (msb : lsb)  — part-select
    #   AscendingRangeSelect / DescendingRangeSelect — indexed part-select
    #   bare expression — bit-select
    inner: Optional[Any] = None
    for c in _iter_children(elem_select):
        if _is_skip_kind(c):
            continue
        inner = c
        break
    if inner is None:
        return None
    k = _kind_local(inner)
    if k.endswith("SimpleRangeSelect"):
        # children: [expr, ':', expr]
        exprs = [c for c in _iter_children(inner) if not _is_skip_kind(c)]
        if len(exprs) >= 2:
            return exprs[0], exprs[1]
        return None
    if k.endswith("AscendingRangeSelect") or k.endswith("DescendingRangeSelect"):
        exprs = [c for c in _iter_children(inner) if not _is_skip_kind(c)]
        if len(exprs) >= 2:
            return exprs[0], exprs[1]
        return None
    if k.endswith("BitSelect"):
        # ``BitSelect`` wraps a single index expression — both bounds equal.
        exprs = [c for c in _iter_children(inner) if not _is_skip_kind(c)]
        if exprs:
            return exprs[0], exprs[0]
        return None
    # bit-select — inner is a bare expression
    return inner, inner


# ---------------------------------------------------------------------------
# Path hashing for stable IDs
# ---------------------------------------------------------------------------


def _flatten_expression_children(node: Any) -> Iterator[Any]:
    """Yield expression-bearing children of *node*, descending through list
    wrappers (``SyntaxList``/``SeparatedList``/``TokenList``) transparently
    and skipping leaf tokens.

    pyslang nests operator operands and concatenation elements under list
    wrappers; the walker treats those wrappers as zero-cost containers so
    operand indexing matches schema-level semantics (operand 0 = LHS).
    """
    for child in _iter_children(node):
        ks = _kind_str(child)
        if ks.startswith("TokenKind."):
            continue
        if ks.endswith("SyntaxList") or ks.endswith("SeparatedList") or ks.endswith("TokenList"):
            yield from _flatten_expression_children(child)
            continue
        yield child


def _hash_path(path: List[Tuple[int, str]]) -> str:
    """Hash a ``[(child_index, syntax_kind), ...]`` path → 8 hex chars."""
    encoded = "|".join(f"{i}:{k}" for i, k in path).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


class V2DataflowWalker:
    """Wave 1 / track A — recursive expression-tree walker.

    Construction takes the same ``known_module_signals`` table v1 uses, so
    the walker can decide whether a name reference resolves to a real
    module-scope signal (drives the ``slice_of`` target). Track C will
    expand on this table for proper cross-reference resolution; track A
    only consumes it for the slice_of target.
    """

    name: str = V2_WALKER_SOURCE

    def __init__(self, known_module_signals: Dict[str, Set[str]]) -> None:
        self._known: Dict[str, Set[str]] = {
            mod: set(sigs) for mod, sigs in (known_module_signals or {}).items()
        }
        # Populated during ``extract`` — (process_id, expr_source_text) ->
        # canonical root entity name. The integration driver reads this to
        # bridge track-B Condition stubs onto track-A Operator/Literal/Index
        # roots emitted from the same expression text within the same
        # process.
        self.text_to_root: Dict[Tuple[str, str], str] = {}

    # ------------------------------------------------------------------ API

    def extract(self, text: str = "", source: str = "") -> ExtractionResult:
        if not text or not text.strip():
            return ExtractionResult()

        try:
            tree = _ps.SyntaxTree.fromText(text)
        except Exception:  # noqa: BLE001
            logger.warning("pyslang parse failed for %s", source, exc_info=True)
            return ExtractionResult()

        entities: List[Entity] = []
        triples: List[Triple] = []

        for mod_decl in _find_top_level_modules(tree.root):
            mod_name = _module_name(mod_decl)
            if mod_name is None:
                continue
            self._extract_module(mod_decl, mod_name, source, entities, triples)

        return ExtractionResult(entities=entities, triples=triples)

    # ------------------------------------------------------------ Internal

    def _extract_module(
        self,
        mod_decl: Any,
        mod_name: str,
        source: str,
        entities_out: List[Entity],
        triples_out: List[Triple],
    ) -> None:
        signals = self._known.get(mod_name, set())

        # Module-level state
        # Literal de-dup table: value-key → entity-name (shared across all
        # processes within this module, per schema doc § Naming).
        literal_dedup: Dict[str, str] = {}
        # Entity de-dup so we don't re-emit the same Operator/Index twice if
        # somehow visited twice (e.g. shared between branches).
        emitted_entities: Set[str] = set()
        # Triple de-dup (subject, predicate, object, operand_index).
        # ``operand_index`` is ``None`` for non-operand triples; for operand
        # edges it carries the int index so the same operator can have
        # operand-0 and operand-1 edges to two distinct children without
        # being collapsed.
        emitted_triples: Set[Tuple[str, str, str, Optional[int]]] = set()

        process_nodes = _collect_process_nodes(mod_decl)
        for proc_idx, (kind_label, node) in enumerate(process_nodes):
            proc_name = f"{mod_name}.{kind_label}_{proc_idx}"
            ctx = _Ctx(
                module=mod_name,
                process=proc_name,
                signals=signals,
                source=source,
                literal_dedup=literal_dedup,
                emitted_entities=emitted_entities,
                emitted_triples=emitted_triples,
                entities_out=entities_out,
                triples_out=triples_out,
                text_to_root=self.text_to_root,
            )
            # Walk every expression descendant of the process body. We use
            # the process node itself as the path root.
            self._visit(node, ctx, path=[])

    # ---- recursion ----

    def _visit(
        self,
        node: Any,
        ctx: "_Ctx",
        path: List[Tuple[int, str]],
    ) -> Optional[str]:
        """Visit *node* and (if it's an expression we care about) emit it.

        Returns the emitted entity name when *node* directly produces a
        node, else ``None`` — callers that want to wire *node* as an operand
        of their parent use the returned name.
        """
        # Skip-kind nodes (SyntaxList, SeparatedList, tokens, ...) carry no
        # semantic content themselves but may *contain* expressions —
        # descend through them transparently without consuming a path slot.
        if _is_skip_kind(node):
            if _kind_str(node).startswith("TokenKind."):
                return None
            kept_idx = 0
            for child in _iter_children(node):
                if _is_skip_kind(child) and _kind_str(child).startswith("TokenKind."):
                    continue
                self._visit(child, ctx, path + [(kept_idx, _kind_local(child))])
                kept_idx += 1
            return None

        # Bit-select / part-select: surface as Index node *before* descending
        # so the inner identifier doesn't get treated as a plain reference.
        if _kind_local(node).endswith("IdentifierSelectName"):
            return self._emit_index(node, ctx, path)

        if _is_literal(node):
            return self._emit_literal(node, ctx)

        if _is_operator(node):
            return self._emit_operator(node, ctx, path)

        # Not an emit-site itself — descend into children, preserving the
        # path so deeper operators get a stable hash from the process root.
        # Drop leaf tokens but transparently descend list wrappers; the
        # ``_visit`` call handles list-wrapper transparency itself.
        kept_idx = 0
        for child in _iter_children(node):
            if _kind_str(child).startswith("TokenKind."):
                continue
            self._visit(child, ctx, path + [(kept_idx, _kind_local(child))])
            kept_idx += 1
        return None

    # ---- emit sites ----

    def _emit_operator(
        self,
        node: Any,
        ctx: "_Ctx",
        path: List[Tuple[int, str]],
    ) -> str:
        kind = _operator_kind(node)
        name = f"{ctx.process}.{_hash_path(path)}"
        if name not in ctx.emitted_entities:
            ctx.emitted_entities.add(name)
            try:
                op_text = str(node).strip()
            except Exception:  # noqa: BLE001
                op_text = ""
            ctx.entities_out.append(
                Entity(
                    name=name,
                    type="Operator",
                    sources=[ctx.source] if ctx.source else [],
                    extractor_source=[V2_WALKER_SOURCE],
                    layer=_AST_LAYER,
                    attributes={"kind": kind, "text": op_text},
                )
            )
            # Track A → integration bridge: index operator name by source text
            # within the process so the integration driver can splice
            # track-B Condition stubs onto the right Operator root.
            ctx.text_to_root.setdefault((ctx.process, op_text), name)

        # Operands = expression-bearing children (transparently descending
        # list wrappers). Index 0 is the leftmost meaningful operand — for
        # binary expressions this is the LHS, matching schema doc § operand
        # semantics. Concatenations and similar collect every list element.
        operand_idx = 0
        kept_child_idx = 0
        for child in _flatten_expression_children(node):
            child_path = path + [(kept_child_idx, _kind_local(child))]
            kept_child_idx += 1
            child_name = self._visit_for_operand(child, ctx, child_path)
            if child_name is None:
                continue
            self._emit_triple(
                ctx,
                subject=name,
                predicate="operand",
                obj=child_name,
                operand_index=operand_idx,
            )
            operand_idx += 1

        return name

    def _visit_for_operand(
        self,
        node: Any,
        ctx: "_Ctx",
        path: List[Tuple[int, str]],
    ) -> Optional[str]:
        """Visit a child that is expected to *yield* an operand node.

        For pure name references (``IdentifierName`` → "a"), we skip
        emitting a node (track C handles cross-references) and return the
        qualified signal name as the operand target — consistent with the
        schema's intent that operand edges target either expression-nodes
        or Signal/Port leaves.
        """
        if _is_skip_kind(node):
            return None

        # Plain identifier reference — operand edge targets the qualified
        # module signal directly. (Track C will reify this as a `references`
        # edge to a declared Signal/Port entity; for track A we just point
        # at the canonical signal name so downstream queries work.)
        if _kind_local(node).endswith("IdentifierName"):
            base = _identifier_name_text(node)
            if base is None:
                return None
            return f"{ctx.module}.{base}"

        # IdentifierSelectName — emit an Index node (slice_of).
        if _kind_local(node).endswith("IdentifierSelectName"):
            return self._emit_index(node, ctx, path)

        if _is_literal(node):
            return self._emit_literal(node, ctx)

        if _is_operator(node):
            return self._emit_operator(node, ctx, path)

        # Wrapper node (e.g. ConditionalPredicate) — descend looking for
        # the first meaningful operand.
        kept_idx = 0
        for child in _iter_children(node):
            if _is_skip_kind(child):
                continue
            child_path = path + [(kept_idx, _kind_local(child))]
            kept_idx += 1
            res = self._visit_for_operand(child, ctx, child_path)
            if res is not None:
                return res
        return None

    def _emit_literal(self, node: Any, ctx: "_Ctx") -> str:
        text = _literal_text(node) or "lit"
        key = _normalise_literal_token(text)
        cached = ctx.literal_dedup.get(key)
        if cached is not None:
            return cached
        name = f"{ctx.module}.lit.{key}"
        ctx.literal_dedup[key] = name
        if name not in ctx.emitted_entities:
            ctx.emitted_entities.add(name)
            ctx.entities_out.append(
                Entity(
                    name=name,
                    type="Literal",
                    sources=[ctx.source] if ctx.source else [],
                    extractor_source=[V2_WALKER_SOURCE],
                    layer=_AST_LAYER,
                    attributes={"text": text},
                )
            )
        # Index by stripped source text so a Condition stub whose text is
        # the literal's text can resolve to this name during integration.
        ctx.text_to_root.setdefault((ctx.process, text.strip()), name)
        return name

    def _emit_index(
        self,
        node: Any,
        ctx: "_Ctx",
        path: List[Tuple[int, str]],
    ) -> Optional[str]:
        base = _identifier_select_base(node)
        if base is None:
            return None
        elem_select = _identifier_select_selector(node)
        if elem_select is None:
            # Treat as plain reference if we can't parse the selector.
            return f"{ctx.module}.{base}"
        bounds = _slice_bounds(elem_select)
        if bounds is None:
            return f"{ctx.module}.{base}"
        msb_expr, lsb_expr = bounds

        # Build a textual slice spec for the Index name. Resolve to literal
        # text where the bound is a literal expression; otherwise fall back
        # to the path-hash so the name remains stable.
        msb_text = _literal_text(msb_expr) if _is_literal(msb_expr) else f"e{_hash_path(path + [(0, 'msb')])}"
        lsb_text = _literal_text(lsb_expr) if _is_literal(lsb_expr) else f"e{_hash_path(path + [(1, 'lsb')])}"

        if msb_text == lsb_text:
            slice_text = f"[{msb_text}]"
        else:
            slice_text = f"[{msb_text}:{lsb_text}]"
        index_name = f"{ctx.module}.{base}.{slice_text}"

        if index_name not in ctx.emitted_entities:
            ctx.emitted_entities.add(index_name)
            try:
                idx_text = str(node).strip()
            except Exception:  # noqa: BLE001
                idx_text = f"{base}{slice_text}"
            ctx.entities_out.append(
                Entity(
                    name=index_name,
                    type="Index",
                    sources=[ctx.source] if ctx.source else [],
                    extractor_source=[V2_WALKER_SOURCE],
                    layer=_AST_LAYER,
                    attributes={"text": slice_text, "source_text": idx_text},
                )
            )
            # Index by full source text (e.g. "data[7:0]") so a Condition or
            # assignment LHS stub with that text resolves to this Index node.
            ctx.text_to_root.setdefault((ctx.process, idx_text), index_name)

        # slice_of target: the qualified base signal (track C will firm up
        # the cross-reference resolution; the name is stable already).
        slice_of_target = f"{ctx.module}.{base}"
        self._emit_triple(
            ctx, subject=index_name, predicate="slice_of", obj=slice_of_target,
        )

        # MSB / LSB: emit literal nodes when bounds are literals; otherwise
        # recursively visit the expression and use its emitted name.
        msb_obj = self._bound_target(msb_expr, ctx, path + [(0, "msb")])
        lsb_obj = (
            msb_obj if msb_expr is lsb_expr
            else self._bound_target(lsb_expr, ctx, path + [(1, "lsb")])
        )
        if msb_obj is not None:
            self._emit_triple(ctx, subject=index_name, predicate="slice_msb", obj=msb_obj)
        if lsb_obj is not None:
            self._emit_triple(ctx, subject=index_name, predicate="slice_lsb", obj=lsb_obj)

        return index_name

    def _bound_target(
        self,
        bound_node: Any,
        ctx: "_Ctx",
        path: List[Tuple[int, str]],
    ) -> Optional[str]:
        if _is_literal(bound_node):
            return self._emit_literal(bound_node, ctx)
        if _kind_local(bound_node).endswith("IdentifierName"):
            txt = _identifier_name_text(bound_node)
            return f"{ctx.module}.{txt}" if txt else None
        if _is_operator(bound_node):
            return self._emit_operator(bound_node, ctx, path)
        return None

    # ---- triple helper ----

    def _emit_triple(
        self,
        ctx: "_Ctx",
        *,
        subject: str,
        predicate: str,
        obj: str,
        operand_index: Optional[int] = None,
    ) -> None:
        key = (subject, predicate, obj, operand_index)
        if key in ctx.emitted_triples:
            return
        ctx.emitted_triples.add(key)
        attributes: Dict[str, Any] = {}
        if operand_index is not None:
            attributes["operand_index"] = operand_index
        ctx.triples_out.append(
            Triple(
                subject=subject,
                predicate=predicate,
                object=obj,
                source=ctx.source,
                extractor_source=V2_WALKER_SOURCE,
                layer=_AST_LAYER,
                attributes=attributes,
            )
        )


def _identifier_name_text(node: Any) -> Optional[str]:
    """First ``Identifier`` token text under an ``IdentifierName``."""
    if not _kind_local(node).endswith("IdentifierName"):
        return None
    for child in _iter_children(node):
        if _kind_str(child).endswith("Identifier") and not _kind_str(child).endswith("Name"):
            return _token_text(child)
    return None


# ---------------------------------------------------------------------------
# Walker context — passes module-scope state through recursion
# ---------------------------------------------------------------------------


class _Ctx:  # noqa: N801 — internal helper, not a dataclass
    """Mutable per-process / per-module scratchpad threaded through walks."""

    __slots__ = (
        "module",
        "process",
        "signals",
        "source",
        "literal_dedup",
        "emitted_entities",
        "emitted_triples",
        "entities_out",
        "triples_out",
        "text_to_root",
    )

    def __init__(
        self,
        *,
        module: str,
        process: str,
        signals: Set[str],
        source: str,
        literal_dedup: Dict[str, str],
        emitted_entities: Set[str],
        emitted_triples: Set[Tuple[str, str, str, Optional[int]]],
        entities_out: List[Entity],
        triples_out: List[Triple],
        text_to_root: Optional[Dict[Tuple[str, str], str]] = None,
    ) -> None:
        self.module = module
        self.process = process
        self.signals = signals
        self.source = source
        self.literal_dedup = literal_dedup
        self.emitted_entities = emitted_entities
        self.emitted_triples = emitted_triples
        self.entities_out = entities_out
        self.triples_out = triples_out
        # (process_id, expression_text) -> root entity name. Populated by
        # _emit_operator / _emit_index / _emit_literal so the integration
        # driver can splice track-B Condition stubs onto the right
        # expression-tree root.
        self.text_to_root = text_to_root if text_to_root is not None else {}
