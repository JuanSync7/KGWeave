# @summary
# V2 statement-level decomposition (Wave 1 / track B).  Walks pyslang
# statement subtrees inside each Process (always_*, initial, final,
# continuous-assign) and emits AST-layer entities — IfStatement,
# CaseStatement, Loop, Branch, Assignment, Condition — together with the
# structural / control-flow edges defined in docs/v2_dataflow_schema.md.
#
# Every emitted Entity carries layer="ast"; every emitted Triple carries
# layer="ast".  Track-A (operator/literal/cross-ref) emits the *real*
# expression internals; this track stubs expression sites with Condition
# nodes carrying source-text payloads so Wave-2 integration can splice in
# track A's Operator/Literal nodes by replacing the stubs.
#
# Exports: SVStatementDecomposer, SV_V2_STMT_LAYER, SV_V2_STMT_SOURCE
# Deps: pyslang (hard), kgweave.knowledge_graph.common
# @end-summary
"""V2 statement-level decomposition walker.

See ``docs/v2_dataflow_schema.md`` for the full v2 schema; this module
implements only the *statement-level* portion of Wave 1.  Operator
decomposition (track A) and cross-reference resolution (track C) are
parallel tracks and run independently.

ID convention (mirrors track A, per schema § "Naming / stable IDs"):

    <module>.<process_kind>_<idx>.<path_hash>

where ``<path_hash>`` is the first 4 hex chars of a sha1 over the path
``[(child_index, syntax_kind), ...]`` from the process root to the node.
The hash changes only when the syntax of the expression itself changes —
stable across reformats and unrelated edits.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from kgweave.knowledge_graph.common import Entity, ExtractionResult, Triple


import pyslang as _ps  # noqa: E402 — hard dep matches the rest of the package


__all__ = ["SVStatementDecomposer", "SV_V2_STMT_LAYER", "SV_V2_STMT_SOURCE"]

logger = logging.getLogger(
    "kgweave.knowledge_graph.extraction.sv_dataflow_v2_statements"
)

# Tag used for layer attribution on every emitted entity / triple.
SV_V2_STMT_LAYER = "ast"
# extractor_source attribution; distinct from the layer tag.
SV_V2_STMT_SOURCE = "sv_dataflow_v2_statements"


# ---------------------------------------------------------------------------
# Pyslang helpers
# ---------------------------------------------------------------------------


def _kind_str(node: Any) -> str:
    k = getattr(node, "kind", None)
    return str(k) if k is not None else ""


def _kind_short(node: Any) -> str:
    """Return ``Foo`` from ``SyntaxKind.Foo``; empty if no kind."""
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


def _children(node: Any) -> List[Any]:
    return list(_iter_children(node))


def _node_text(node: Any) -> str:
    try:
        return str(node).strip()
    except Exception:  # noqa: BLE001
        return ""


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
            name_tok = getattr(c, "name", None)
            if name_tok is not None:
                txt = getattr(name_tok, "valueText", None)
                if isinstance(txt, str) and txt.strip():
                    return txt.strip()
    return None


# ---------------------------------------------------------------------------
# Process discovery (mirrors v1 conventions; adds initial / final)
# ---------------------------------------------------------------------------


_PROCESS_KIND_TABLE: Tuple[Tuple[str, str], ...] = (
    ("AlwaysFFBlock", "always_ff"),
    ("AlwaysCombBlock", "always_comb"),
    ("AlwaysLatchBlock", "always_latch"),
    ("AlwaysBlock", "always"),
    ("InitialBlock", "initial"),
    ("FinalBlock", "final"),
    ("ContinuousAssign", "assign"),
)


def _is_continuous_assign_process(process_id: str) -> bool:
    """``<mod>.assign_<idx>`` matches; ``<mod>.always_ff_<idx>`` does not.

    Robust against module names that themselves contain ``assign_``.
    """
    tail = process_id.rsplit(".", 1)[-1]
    if not tail.startswith("assign_"):
        return False
    suffix = tail[len("assign_"):]
    return suffix.isdigit()


def _classify_process(node: Any) -> Optional[str]:
    k = _kind_str(node)
    for suffix, label in _PROCESS_KIND_TABLE:
        if k.endswith(suffix):
            return label
    return None


def _collect_processes(mod_decl: Any) -> List[Tuple[str, Any]]:
    """Collect (kind_label, node) for each process inside *mod_decl*.

    Does not descend into nested module declarations.
    """
    out: List[Tuple[str, Any]] = []

    def walk(node: Any) -> None:
        k = _kind_str(node)
        if "ModuleDeclaration" in k and node is not mod_decl:
            return
        label = _classify_process(node)
        if label is not None:
            out.append((label, node))
            # Don't descend into the body — body is walked by decompose_process.
            return
        for c in _iter_children(node):
            walk(c)

    walk(mod_decl)
    return out


# ---------------------------------------------------------------------------
# Decomposer
# ---------------------------------------------------------------------------


# Statement kind suffixes we recognise as control flow.
_IF_SUFFIX = "ConditionalStatement"
_CASE_SUFFIX = "CaseStatement"
_FOR_SUFFIX = "ForLoopStatement"
_LOOP_SUFFIX = "LoopStatement"  # while / repeat
_FOREVER_SUFFIX = "ForeverStatement"
_FOREACH_SUFFIX = "ForeachLoopStatement"
_SEQ_BLOCK_SUFFIX = "SequentialBlockStatement"
_PAR_BLOCK_SUFFIX = "ParallelBlockStatement"
_EXPR_STMT_SUFFIX = "ExpressionStatement"
_TIMING_STMT_SUFFIX = "TimingControlStatement"

_NB_ASSIGN_SUFFIX = "NonblockingAssignmentExpression"
_BLOCKING_ASSIGN_SUFFIX = "AssignmentExpression"

_ELSE_CLAUSE_SUFFIX = "ElseClause"
_STD_CASE_ITEM_SUFFIX = "StandardCaseItem"
_DEFAULT_CASE_ITEM_SUFFIX = "DefaultCaseItem"


@dataclass
class _Ctx:
    """Mutable walk-state for one process."""

    mod_name: str
    process_id: str
    source: str
    entities: List[Entity] = field(default_factory=list)
    triples: List[Triple] = field(default_factory=list)
    # ordered list of Branch IDs from outermost -> innermost
    branch_path: List[str] = field(default_factory=list)
    # cache: path_hash -> int counter for collisions (defensive; sha1[:4] is rarely
    # ambiguous within a single process but we still need stable disambiguation).
    _id_seen: dict = field(default_factory=dict)
    # path of (child_index, syntax_kind_short) tuples from process root.
    _path: List[Tuple[int, str]] = field(default_factory=list)


class SVStatementDecomposer:
    """Wave-1 / track-B decomposer.

    Usage::

        dec = SVStatementDecomposer()
        result = dec.extract(text=source_text, source="<file>")

    Output entities and triples are tagged ``layer="ast"``.
    """

    name: str = SV_V2_STMT_SOURCE

    # ---------------------------------------------------------------- API

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

    # ---------------------------------------------------------- Module pass

    def _extract_module(
        self,
        mod_decl: Any,
        mod_name: str,
        source: str,
        entities_out: List[Entity],
        triples_out: List[Triple],
    ) -> None:
        for idx, (kind_label, proc_node) in enumerate(_collect_processes(mod_decl)):
            proc_id = f"{mod_name}.{kind_label}_{idx}"
            ctx = _Ctx(mod_name=mod_name, process_id=proc_id, source=source)
            # Walk children of the process node (skipping the process node itself
            # because it is already represented as a v1 Process entity).
            for child_idx, child in enumerate(_iter_children(proc_node)):
                self._walk_statement(child, ctx, child_idx, parent_id=proc_id,
                                     parent_pred="contains")
            entities_out.extend(ctx.entities)
            triples_out.extend(ctx.triples)

    # ------------------------------------------------- Statement dispatcher

    def _walk_statement(
        self,
        node: Any,
        ctx: _Ctx,
        child_index: int,
        parent_id: str,
        parent_pred: str,
    ) -> None:
        """Dispatch a statement-shaped node.

        ``parent_id`` / ``parent_pred`` are the edge that should link from
        the parent into whatever node we materialise.  For "transparent"
        constructs (sequential blocks, expression statements wrapping an
        assignment, timing-control statements wrapping a body), we don't
        emit a node — we forward the parent edge to the inner statement.
        """
        kind = _kind_short(node)
        if not kind:
            return

        # Push the path step for stable ID hashing.
        ctx._path.append((child_index, kind))
        try:
            self._dispatch(node, kind, ctx, parent_id, parent_pred)
        finally:
            ctx._path.pop()

    def _dispatch(
        self,
        node: Any,
        kind: str,
        ctx: _Ctx,
        parent_id: str,
        parent_pred: str,
    ) -> None:
        # --- Transparent containers (skip per schema: begin/end flatten) ---
        if kind.endswith(_SEQ_BLOCK_SUFFIX) or kind.endswith(_PAR_BLOCK_SUFFIX):
            for i, c in enumerate(_iter_children(node)):
                self._walk_statement(c, ctx, i, parent_id, parent_pred)
            return

        # TimingControlStatement wraps a real body — forward the parent edge.
        if kind.endswith(_TIMING_STMT_SUFFIX):
            for i, c in enumerate(_iter_children(node)):
                ck = _kind_short(c)
                # Skip the timing-control header (event-control, etc.).
                if ck.endswith("Statement") or ck.endswith(_SEQ_BLOCK_SUFFIX):
                    self._walk_statement(c, ctx, i, parent_id, parent_pred)
            return

        # ExpressionStatement (typically wraps an assignment expression).
        if kind.endswith(_EXPR_STMT_SUFFIX):
            for i, c in enumerate(_iter_children(node)):
                ck = _kind_short(c)
                if ck.endswith(_NB_ASSIGN_SUFFIX) or ck.endswith(
                    _BLOCKING_ASSIGN_SUFFIX
                ):
                    self._walk_statement(c, ctx, i, parent_id, parent_pred)
            return

        # --- Assignment expressions (procedural and continuous bodies) ---
        if kind.endswith(_NB_ASSIGN_SUFFIX):
            self._emit_assignment(node, ctx, parent_id, parent_pred,
                                  assign_kind="nonblocking")
            return
        if kind.endswith(_BLOCKING_ASSIGN_SUFFIX):
            # ContinuousAssign also wraps an AssignmentExpression — distinguish
            # by the process kind.  The process_id terminates in
            # ``.assign_<idx>`` for continuous-assign processes (see
            # _PROCESS_KIND_TABLE: label "assign").
            assign_kind = (
                "continuous"
                if _is_continuous_assign_process(ctx.process_id)
                else "blocking"
            )
            self._emit_assignment(node, ctx, parent_id, parent_pred,
                                  assign_kind=assign_kind)
            return

        # --- Control flow ---
        if kind.endswith(_IF_SUFFIX):
            self._emit_if_chain(node, ctx, parent_id, parent_pred)
            return
        if kind.endswith(_CASE_SUFFIX):
            self._emit_case(node, ctx, parent_id, parent_pred)
            return
        if (
            kind.endswith(_FOR_SUFFIX)
            or kind.endswith(_FOREACH_SUFFIX)
            or kind.endswith(_FOREVER_SUFFIX)
            or kind.endswith(_LOOP_SUFFIX)
        ):
            self._emit_loop(node, ctx, parent_id, parent_pred)
            return

        # --- Otherwise: recurse generically (lets us discover nested control
        # flow inside e.g. ContinuousAssign). ---
        for i, c in enumerate(_iter_children(node)):
            self._walk_statement(c, ctx, i, parent_id, parent_pred)

    # --------------------------------------------------------- Stable IDs

    def _make_id(self, ctx: _Ctx, suffix: str = "") -> str:
        """Build ``<process_id>.<path_hash>[<suffix>]``."""
        path_repr = ";".join(f"{i}:{k}" for i, k in ctx._path)
        digest = hashlib.sha1(path_repr.encode("utf-8")).hexdigest()[:4]
        # Disambiguate any rare 4-char collision within a process by appending
        # a counter.  Counter only fires on actual collisions.
        base = f"{ctx.process_id}.{digest}"
        seen = ctx._id_seen.setdefault(base, 0)
        ctx._id_seen[base] = seen + 1
        if seen == 0:
            return f"{base}{suffix}"
        return f"{base}_{seen}{suffix}"

    # ------------------------------------------------------ Emission helpers

    def _add_entity(self, ctx: _Ctx, name: str, type_: str,
                    attributes: Optional[Dict[str, Any]] = None) -> None:
        ctx.entities.append(
            Entity(
                name=name,
                type=type_,
                sources=[ctx.source] if ctx.source else [],
                extractor_source=[SV_V2_STMT_SOURCE],
                layer=SV_V2_STMT_LAYER,
                attributes=dict(attributes) if attributes else {},
            )
        )

    def _add_triple(self, ctx: _Ctx, subj: str, pred: str, obj: str) -> None:
        ctx.triples.append(
            Triple(
                subject=subj,
                predicate=pred,
                object=obj,
                source=ctx.source,
                extractor_source=SV_V2_STMT_SOURCE,
                layer=SV_V2_STMT_LAYER,
            )
        )

    def _emit_condition(self, ctx: _Ctx, expr_node: Any, target_id: str) -> str:
        """Emit a placeholder Condition node and a ``condition_of`` edge.

        Track A will replace this with operand-decomposed Operator/Literal
        nodes during Wave-2 integration.
        """
        text = _node_text(expr_node)
        cond_id = self._make_id(ctx, suffix=".cond")
        self._add_entity(ctx, cond_id, "Condition",
                         attributes={"text": text})
        self._add_triple(ctx, cond_id, "condition_of", target_id)
        return cond_id

    def _emit_expr_stub(self, ctx: _Ctx, expr_node: Any,
                        type_: str = "Condition", suffix: str = ".expr") -> str:
        """Emit a generic placeholder expression node (no condition_of edge).

        Used for case selectors, loop bounds, assignment LHS/RHS, case_value.
        """
        text = _node_text(expr_node)
        eid = self._make_id(ctx, suffix=suffix)
        self._add_entity(ctx, eid, type_, attributes={"text": text})
        return eid

    # ------------------------------------------------------------ IfStatement

    def _emit_if_chain(self, node: Any, ctx: _Ctx,
                       parent_id: str, parent_pred: str) -> None:
        """Materialise an entire if/else-if/else chain as one IfStatement node.

        Pyslang nests ``ConditionalStatement`` recursively via ``ElseClause``;
        we walk that chain and emit ordered ``then_branch`` / ``elif_branch``
        / ``else_branch`` edges.
        """
        if_id = self._make_id(ctx, suffix=".if")
        self._add_entity(ctx, if_id, "IfStatement")
        self._add_triple(ctx, parent_id, parent_pred, if_id)

        # First arm: "then" of the outermost ConditionalStatement.
        self._emit_if_arm(node, ctx, if_id, arm_pred="then_branch",
                          chain_index=0)

        # Walk down ElseClause chain.
        chain_index = 1
        cur = self._find_else_clause(node)
        while cur is not None:
            inner = self._else_inner(cur)
            inner_kind = _kind_short(inner) if inner is not None else ""
            if inner is None:
                break
            if inner_kind.endswith(_IF_SUFFIX):
                # else-if: emit elif_branch with the inner if's then-arm body
                # AND keep walking the chain.
                self._emit_if_arm(inner, ctx, if_id, arm_pred="elif_branch",
                                  chain_index=chain_index)
                chain_index += 1
                cur = self._find_else_clause(inner)
            else:
                # Plain else: a single Branch, no Condition.
                self._emit_else_arm(inner, ctx, if_id, chain_index)
                cur = None

    @staticmethod
    def _find_else_clause(cond_stmt: Any) -> Optional[Any]:
        for c in _iter_children(cond_stmt):
            if _kind_short(c).endswith(_ELSE_CLAUSE_SUFFIX):
                return c
        return None

    @staticmethod
    def _else_inner(else_clause: Any) -> Optional[Any]:
        """Return the statement nested inside an ElseClause (skip the else token)."""
        for c in _iter_children(else_clause):
            ck = _kind_short(c)
            # Skip the ElseKeyword token.
            if ck and not ck.endswith("Keyword"):
                return c
        return None

    def _emit_if_arm(
        self,
        cond_stmt: Any,
        ctx: _Ctx,
        if_id: str,
        arm_pred: str,
        chain_index: int,
    ) -> None:
        """Emit a Branch + condition for either the then-arm of the outer if,
        or the body of an else-if's inner ConditionalStatement."""
        # Push a synthetic path step so this branch's ID hash is unique
        # within the if-chain.
        ctx._path.append((chain_index, f"Branch_{arm_pred}"))
        try:
            branch_id = self._make_id(ctx, suffix=".br")
            self._add_entity(
                ctx, branch_id, "Branch",
                attributes={"branch_path": list(ctx.branch_path)},
            )
            self._add_triple(ctx, if_id, arm_pred, branch_id)

            # Emit condition (the ConditionalPredicate / first parenthesized expr).
            pred_node = self._conditional_predicate(cond_stmt)
            if pred_node is not None:
                self._emit_condition(ctx, pred_node, branch_id)

            # Walk the body of the conditional (the statement inside, post-`)`).
            body = self._conditional_body(cond_stmt)
            if body is not None:
                ctx.branch_path.append(branch_id)
                try:
                    self._walk_statement(body, ctx, 0, parent_id=branch_id,
                                         parent_pred="body_of")
                finally:
                    ctx.branch_path.pop()
        finally:
            ctx._path.pop()

    def _emit_else_arm(
        self,
        body: Any,
        ctx: _Ctx,
        if_id: str,
        chain_index: int,
    ) -> None:
        ctx._path.append((chain_index, "Branch_else_branch"))
        try:
            branch_id = self._make_id(ctx, suffix=".br")
            self._add_entity(
                ctx, branch_id, "Branch",
                attributes={"branch_path": list(ctx.branch_path)},
            )
            self._add_triple(ctx, if_id, "else_branch", branch_id)

            ctx.branch_path.append(branch_id)
            try:
                self._walk_statement(body, ctx, 0, parent_id=branch_id,
                                     parent_pred="body_of")
            finally:
                ctx.branch_path.pop()
        finally:
            ctx._path.pop()

    @staticmethod
    def _conditional_predicate(cond_stmt: Any) -> Optional[Any]:
        for c in _iter_children(cond_stmt):
            ck = _kind_short(c)
            if ck.endswith("ConditionalPredicate"):
                return c
        return None

    @staticmethod
    def _conditional_body(cond_stmt: Any) -> Optional[Any]:
        """Return the statement that is the body of an if (the part after `)`)."""
        seen_close = False
        for c in _iter_children(cond_stmt):
            ck = _kind_short(c)
            if ck.endswith("CloseParenthesis"):
                seen_close = True
                continue
            if not seen_close:
                continue
            if ck.endswith(_ELSE_CLAUSE_SUFFIX):
                continue
            if ck.endswith("Keyword"):
                continue
            # First non-keyword node after `)` and before the else-clause.
            return c
        return None

    # -------------------------------------------------------- CaseStatement

    def _emit_case(self, node: Any, ctx: _Ctx,
                   parent_id: str, parent_pred: str) -> None:
        case_id = self._make_id(ctx, suffix=".case")
        case_kind = self._classify_case_kind(node)
        self._add_entity(
            ctx, case_id, "CaseStatement",
            attributes={"case_kind": case_kind},
        )
        self._add_triple(ctx, parent_id, parent_pred, case_id)

        # Selector — first non-keyword, non-paren expression child.
        sel_expr = self._case_selector(node)
        if sel_expr is not None:
            sel_id = self._emit_expr_stub(ctx, sel_expr, type_="Condition",
                                          suffix=".selector")
            self._add_triple(ctx, case_id, "selector", sel_id)

        # Items — StandardCaseItem / DefaultCaseItem in source order.
        item_index = 0
        for c in _iter_children(node):
            ck = _kind_short(c)
            if ck.endswith(_STD_CASE_ITEM_SUFFIX):
                self._emit_case_item(c, ctx, case_id, item_index,
                                     is_default=False)
                item_index += 1
            elif ck.endswith(_DEFAULT_CASE_ITEM_SUFFIX):
                self._emit_case_item(c, ctx, case_id, item_index,
                                     is_default=True)
                item_index += 1
            else:
                # Items can be wrapped in a SyntaxList — recurse one level.
                if "SyntaxList" in _kind_str(c):
                    for ic in _iter_children(c):
                        ick = _kind_short(ic)
                        if ick.endswith(_STD_CASE_ITEM_SUFFIX):
                            self._emit_case_item(ic, ctx, case_id, item_index,
                                                 is_default=False)
                            item_index += 1
                        elif ick.endswith(_DEFAULT_CASE_ITEM_SUFFIX):
                            self._emit_case_item(ic, ctx, case_id, item_index,
                                                 is_default=True)
                            item_index += 1

    @staticmethod
    def _classify_case_kind(node: Any) -> str:
        """Encode the case modifier (case / casex / casez / unique / priority)."""
        kinds: List[str] = []
        for c in _iter_children(node):
            ck = _kind_short(c)
            if not ck.endswith("Keyword"):
                continue
            low = ck.lower()
            if "casex" in low:
                kinds.append("casex")
            elif "casez" in low:
                kinds.append("casez")
            elif "case" in low and "endcase" not in low:
                kinds.append("case")
            elif "unique" in low:
                kinds.append("unique")
            elif "priority" in low:
                kinds.append("priority")
        # Compose: "unique_case", "priority_casez", or just "case".
        if not kinds:
            return "case"
        if len(kinds) == 1:
            return kinds[0]
        return "_".join(kinds)

    @staticmethod
    def _case_selector(node: Any) -> Optional[Any]:
        seen_open = False
        for c in _iter_children(node):
            ck = _kind_short(c)
            if ck.endswith("OpenParenthesis"):
                seen_open = True
                continue
            if not seen_open:
                continue
            if ck.endswith("CloseParenthesis"):
                return None
            if ck.endswith("Keyword"):
                continue
            return c
        return None

    def _emit_case_item(
        self,
        item_node: Any,
        ctx: _Ctx,
        case_id: str,
        item_index: int,
        is_default: bool,
    ) -> None:
        ctx._path.append((item_index,
                          "Branch_default" if is_default else "Branch_case_item"))
        try:
            branch_id = self._make_id(ctx, suffix=".br")
            self._add_entity(
                ctx, branch_id, "Branch",
                attributes={"branch_path": list(ctx.branch_path)},
            )
            pred = "default_branch" if is_default else "case_item"
            self._add_triple(ctx, case_id, pred, branch_id)

            if not is_default:
                # Emit a case_value stub for each match expression.
                for c in _iter_children(item_node):
                    if "SeparatedList" in _kind_str(c):
                        for vc in _iter_children(c):
                            vk = _kind_short(vc)
                            if vk.endswith("Comma") or vk.endswith("Colon"):
                                continue
                            cv_id = self._emit_expr_stub(
                                ctx, vc, type_="Condition", suffix=".case_value"
                            )
                            self._add_triple(ctx, branch_id, "case_value", cv_id)
                        break

            # Walk body — last non-keyword, non-list child of the case item.
            body = self._case_item_body(item_node)
            if body is not None:
                ctx.branch_path.append(branch_id)
                try:
                    self._walk_statement(body, ctx, 0, parent_id=branch_id,
                                         parent_pred="body_of")
                finally:
                    ctx.branch_path.pop()
        finally:
            ctx._path.pop()

    @staticmethod
    def _case_item_body(item_node: Any) -> Optional[Any]:
        last = None
        for c in _iter_children(item_node):
            ck = _kind_short(c)
            if ck.endswith("Keyword") or ck.endswith("Colon") or ck.endswith("Comma"):
                continue
            if "SeparatedList" in _kind_str(c) or "TokenList" in _kind_str(c):
                continue
            last = c
        return last

    # ----------------------------------------------------------------- Loop

    def _emit_loop(self, node: Any, ctx: _Ctx,
                   parent_id: str, parent_pred: str) -> None:
        loop_id = self._make_id(ctx, suffix=".loop")
        loop_kind = self._classify_loop_kind(node)
        self._add_entity(
            ctx, loop_id, "Loop",
            attributes={"loop_kind": loop_kind},
        )
        self._add_triple(ctx, parent_id, parent_pred, loop_id)

        # Walk the body — last child statement.
        body = self._loop_body(node)
        if body is not None:
            self._walk_statement(body, ctx, 0, parent_id=loop_id,
                                 parent_pred="body_of")

    @staticmethod
    def _classify_loop_kind(node: Any) -> str:
        # Inspect keyword tokens to find for/while/repeat/forever/foreach.
        for c in _iter_children(node):
            ck = _kind_short(c)
            low = ck.lower()
            if low.endswith("keyword"):
                # Order matters — check long-prefix variants first so
                # ``foreverkeyword`` doesn't match ``for``.
                for tag in ("foreach", "forever", "while", "repeat", "for", "do"):
                    if tag in low:
                        return tag
        # Fall back to the syntax kind.
        kind = _kind_short(node).lower()
        for tag in ("foreach", "forever", "while", "repeat", "for"):
            if tag in kind:
                return tag
        return "loop"

    @staticmethod
    def _loop_body(node: Any) -> Optional[Any]:
        last = None
        for c in _iter_children(node):
            ck = _kind_short(c)
            # Body is the trailing statement; skip keywords / parens / lists.
            if ck.endswith("Keyword"):
                continue
            if ck.endswith("OpenParenthesis") or ck.endswith("CloseParenthesis"):
                continue
            last = c
        return last

    # ------------------------------------------------------------ Assignment

    def _emit_assignment(
        self,
        node: Any,
        ctx: _Ctx,
        parent_id: str,
        parent_pred: str,
        assign_kind: str,
    ) -> None:
        a_id = self._make_id(ctx, suffix=".assign")
        self._add_entity(
            ctx, a_id, "Assignment",
            attributes={
                "assign_kind": assign_kind,
                "branch_path": list(ctx.branch_path),
            },
        )
        self._add_triple(ctx, parent_id, parent_pred, a_id)

        lhs_node, rhs_node = self._assign_lhs_rhs(node)
        if lhs_node is not None:
            lhs_id = self._emit_expr_stub(ctx, lhs_node, type_="Condition",
                                          suffix=".lhs")
            self._add_triple(ctx, a_id, "lhs", lhs_id)
        if rhs_node is not None:
            rhs_id = self._emit_expr_stub(ctx, rhs_node, type_="Condition",
                                          suffix=".rhs")
            self._add_triple(ctx, a_id, "rhs", rhs_id)

    @staticmethod
    def _assign_lhs_rhs(node: Any) -> Tuple[Optional[Any], Optional[Any]]:
        lhs: Optional[Any] = None
        rhs: Optional[Any] = None
        seen_op = False
        for c in _iter_children(node):
            ck = _kind_short(c)
            if not seen_op:
                # Operator tokens: Equals / LessThanEquals / EqualsEquals ...
                if ck.endswith("Equals") or ck.endswith("LessThanEquals"):
                    seen_op = True
                    continue
                if not ck.endswith("Keyword") and not ck.endswith("SyntaxList"):
                    if lhs is None:
                        lhs = c
                continue
            # After the operator, take the first non-trivia child as RHS.
            if ck.endswith("SyntaxList"):
                continue
            if rhs is None:
                rhs = c
        return lhs, rhs

