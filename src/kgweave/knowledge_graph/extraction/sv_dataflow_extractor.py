# @summary
# Intra-module SystemVerilog dataflow extractor (v1, syntax-tree only).
# Emits drives_signal(<module>.<src>, <module>.<dst>) plus Process entities
# and assigned_in(<module>.<dst>, <module>.<process_id>) anchors.
# Exports: SVDataflowExtractor, SV_DATAFLOW_SOURCE
# Deps: pyslang (hard), kgweave.knowledge_graph.common
# @end-summary
"""SystemVerilog intra-module dataflow extractor (v1).

Walks pyslang's *syntax tree* — no elaboration — for every module declaration
in a source string, picks out continuous assigns and ``always_*`` blocks, and
emits whole-signal forward-direction dataflow edges:

* ``drives_signal(<module>.<rhs>, <module>.<lhs>)`` — for every (RHS identifier,
  LHS target) pair within an assignment, deduplicated per pair.
* ``Process`` entities — one per ``always_*`` block / continuous-assign group,
  named ``<module>.<process_kind>_<idx>`` where ``idx`` is a stable
  per-module counter ordered by source position.
* ``assigned_in(<module>.<lhs>, <module>.<process_id>)`` — anchors each LHS
  target to the writing process.

v1 scope (HARD-PINNED):

* Whole-signal granularity. ``x[3:0] = a;`` collapses to ``drives_signal(m.a, m.x)``.
* Definition-relative naming. Both endpoints scoped to the surrounding module.
* Module-boundary intra-only. Cross-module connectivity remains the
  responsibility of the existing ``connects_to`` / ``drives`` predicates.
* Conditional drives: any signal that appears as an LHS in any branch is a
  driver. No per-branch guard tracking.
* Function/task LHS, package-scope reads, and other un-resolvable identifiers
  are filtered out via the construction-time signal table.
* Generate blocks are walked; iteration is collapsed (no parameter awareness).

Heuristics applied:

* **Bit-slice / part-select** — ``IdentifierSelectName`` LHS collapses to its
  base identifier (the first ``Identifier`` token). ``ElementSelect`` /
  ``RangeSelect`` on the RHS likewise contributes only the inner identifier.
* **Loop variables** — filtered implicitly because they are not present in
  the construction-time module-signal table.
* **Function calls** — the first child of an ``InvocationExpression`` is the
  callable's name; we skip it during RHS identifier collection so the
  function name isn't treated as a value source.
* **Unknown identifiers** — anything that doesn't resolve to a module signal
  in the supplied table is dropped. Keeps the graph free of dangling nodes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from kgweave.knowledge_graph.common import Entity, ExtractionResult, Triple


import pyslang as _ps  # noqa: E402 — hard dep matches the rest of the package


__all__ = ["SVDataflowExtractor", "SV_DATAFLOW_SOURCE"]

logger = logging.getLogger("kgweave.knowledge_graph.extraction.sv_dataflow")

SV_DATAFLOW_SOURCE = "sv_dataflow"


# ---------------------------------------------------------------------------
# Pyslang helpers (mirror sv_connectivity / parser_extractor conventions)
# ---------------------------------------------------------------------------


def _kind_str(node: Any) -> str:
    k = getattr(node, "kind", None)
    return str(k) if k is not None else ""


def _iter_children(node: Any) -> Iterator[Any]:
    try:
        for c in node:
            yield c
    except TypeError:
        return


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


def _is_identifier_token(tok: Any) -> bool:
    """Return True iff *tok* is a pyslang ``TokenKind.Identifier``."""
    return _kind_str(tok).endswith("Identifier") and not _kind_str(tok).endswith("Name")


def _find_top_level_modules(root: Any) -> List[Any]:
    """Yield each top-level ``ModuleDeclaration`` in the syntax tree."""
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


# ---------------------------------------------------------------------------
# Identifier extraction
# ---------------------------------------------------------------------------

# SyntaxKind suffixes we treat as "this is a write target / source expression".
_LHS_NAME_KINDS = ("IdentifierName", "IdentifierSelectName")

# Statement / expression kinds carrying an LHS = RHS form.
_ASSIGN_KINDS = (
    "AssignmentExpression",
    "NonblockingAssignmentExpression",
    # pyslang occasionally uses the bare name; we stay conservative.
)

# Block kinds that group statements producing a Process entity.
_ALWAYS_KIND_TO_LABEL = {
    "AlwaysFFBlock": "always_ff",
    "AlwaysCombBlock": "always_comb",
    "AlwaysLatchBlock": "always_latch",
    "AlwaysBlock": "always",
}


def _base_identifier_from_lhs(lhs_node: Any) -> Optional[str]:
    """Return the base signal name for an assignment LHS.

    Handles both ``IdentifierName`` (whole-signal LHS) and
    ``IdentifierSelectName`` (bit-slice / element-select LHS), in which case
    the first ``Identifier`` token under the node is the base name.
    """
    k = _kind_str(lhs_node)
    if k.endswith("IdentifierName") or k.endswith("IdentifierSelectName"):
        for child in _iter_children(lhs_node):
            if _is_identifier_token(child):
                txt = _token_text(child)
                if txt:
                    return txt
        # Fallback: pyslang sometimes exposes ``.identifier`` directly.
        ident = getattr(lhs_node, "identifier", None)
        return _token_text(ident)
    return None


def _is_invocation(node: Any) -> bool:
    return _kind_str(node).endswith("InvocationExpression")


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


class SVDataflowExtractor:
    """Intra-module SystemVerilog dataflow extractor (v1).

    Construction takes a ``known_module_signals`` table that maps every
    module name to the set of signal/port identifiers declared at module
    scope. The table is the source-of-truth for filtering — anything not in
    it (loop variables, function names, package constants, cross-module
    references) is dropped.

    Run ``slang`` / ``sv_parser`` extraction first to populate this table.
    """

    name: str = SV_DATAFLOW_SOURCE

    def __init__(self, known_module_signals: Dict[str, Set[str]]) -> None:
        self._known: Dict[str, Set[str]] = {
            mod: set(sigs) for mod, sigs in (known_module_signals or {}).items()
        }

    # ------------------------------------------------------------------ API

    def extract(self, text: str = "", source: str = "") -> ExtractionResult:
        if not text or not text.strip():
            return ExtractionResult()

        # Defensive: empty signal table + non-trivial source = misuse.
        if not self._known:
            raise ValueError(
                "SVDataflowExtractor requires populated module-signal table — "
                "run slang/parser extraction first"
            )

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

    def extract_entities(self, text: str) -> Set[str]:
        return {e.name for e in self.extract(text=text).entities}

    def extract_relations(self, text: str, known_entities: Set[str]) -> List[Triple]:
        return self.extract(text=text).triples

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
        if not signals:
            # Module known to elaborator but no signal members — nothing to do.
            return

        # Collect process-bearing nodes (continuous assigns + always_*) in
        # source order, walking through generate blocks.
        process_nodes = self._collect_process_nodes(mod_decl)

        # Build a fresh dedup set per module so dedup is *within* a module.
        emitted_pairs: Set[Tuple[str, str]] = set()

        for idx, (kind_label, node) in enumerate(process_nodes):
            proc_name = f"{mod_name}.{kind_label}_{idx}"
            entities_out.append(self._make_process_entity(proc_name, kind_label,
                                                          mod_name, source))
            self._emit_for_process(
                node=node,
                kind_label=kind_label,
                proc_name=proc_name,
                mod_name=mod_name,
                signals=signals,
                source=source,
                emitted_pairs=emitted_pairs,
                triples_out=triples_out,
            )

    def _collect_process_nodes(self, mod_decl: Any) -> List[Tuple[str, Any]]:
        """Return [(kind_label, node)] in source order for every assign /
        always_* anywhere inside *mod_decl* (incl. generate blocks).

        Does NOT descend into nested ``ModuleDeclaration`` nodes (those are
        treated as separate top-level modules at the dispatcher level)."""
        results: List[Tuple[str, Any]] = []

        def walk(node: Any) -> None:
            k = _kind_str(node)
            # Don't descend into nested module declarations.
            if "ModuleDeclaration" in k and node is not mod_decl:
                return
            if k.endswith("ContinuousAssign"):
                results.append(("assign", node))
                # don't descend further — RHS/LHS are visited in extract step
                return
            for label_suffix, label in _ALWAYS_KIND_TO_LABEL.items():
                if k.endswith(label_suffix):
                    results.append((label, node))
                    return
            for c in _iter_children(node):
                walk(c)

        walk(mod_decl)
        return results

    def _emit_for_process(
        self,
        node: Any,
        kind_label: str,
        proc_name: str,
        mod_name: str,
        signals: Set[str],
        source: str,
        emitted_pairs: Set[Tuple[str, str]],
        triples_out: List[Triple],
    ) -> None:
        """Walk *node* and emit drives_signal / assigned_in triples.

        v1 model:
          * Collect every assignment node in the process subtree. Each
            assignment's LHS contributes a write target (after bit-slice
            collapse).
          * Collect every identifier in the process subtree EXCEPT the
            base LHS identifier of an assignment node. Predicate signals
            in ``if (cond)`` and clock identifiers in ``@(posedge clk)``
            naturally surface this way.
          * For each (rhs identifier, lhs target) pair, emit drives_signal,
            module-level deduped.
        """
        # Step 1: discover assignment nodes & their LHS base names.
        assignments: List[Any] = []

        def find_assignments(n: Any) -> None:
            k = _kind_str(n)
            for ak in _ASSIGN_KINDS:
                if k.endswith(ak):
                    assignments.append(n)
                    break
            for c in _iter_children(n):
                find_assignments(c)

        find_assignments(node)

        lhs_targets: List[Tuple[str, Any]] = []  # (lhs_base_name, lhs_node)
        for a in assignments:
            lhs_node = self._lhs_subnode(a)
            if lhs_node is None:
                continue
            base = _base_identifier_from_lhs(lhs_node)
            if base is None or base not in signals:
                continue
            lhs_targets.append((base, lhs_node))

        # Step 2: collect every identifier in the process subtree, skipping
        # the LHS base identifier of every assignment.
        skip_nodes = {id(lhs_node) for _, lhs_node in lhs_targets}
        rhs_idents: List[str] = self._collect_idents_skipping(node, skip_nodes)

        # Step 3: emit assigned_in (one per distinct LHS) and drives_signal.
        proc_assigned: Set[str] = set()
        for base, _ in lhs_targets:
            qualified = f"{mod_name}.{base}"
            if qualified in proc_assigned:
                continue
            proc_assigned.add(qualified)
            triples_out.append(
                Triple(
                    subject=qualified,
                    predicate="assigned_in",
                    object=proc_name,
                    source=source,
                    extractor_source=SV_DATAFLOW_SOURCE,
                    layer=SV_DATAFLOW_SOURCE,
                )
            )

        # drives_signal cross-product (rhs_ident -> each LHS target).
        rhs_filtered = [r for r in rhs_idents if r in signals]
        # dedup per process before cross-product to keep triple count tame
        seen_rhs: Set[str] = set()
        rhs_unique: List[str] = []
        for r in rhs_filtered:
            if r in seen_rhs:
                continue
            seen_rhs.add(r)
            rhs_unique.append(r)

        for base, _ in lhs_targets:
            for rname in rhs_unique:
                if rname == base:
                    continue
                key = (f"{mod_name}.{rname}", f"{mod_name}.{base}")
                if key in emitted_pairs:
                    continue
                emitted_pairs.add(key)
                triples_out.append(
                    Triple(
                        subject=key[0],
                        predicate="drives_signal",
                        object=key[1],
                        source=source,
                        extractor_source=SV_DATAFLOW_SOURCE,
                        layer=SV_DATAFLOW_SOURCE,
                    )
                )
                # V2 unification (Wave 2 / track E): dual-emit `data_flows`
                # so a BFS over `data_flows` covers intra-module dataflow
                # alongside cross-module port bindings. Tag layer="slang"
                # per docs/v2_dataflow_schema.md § "Layering". Legacy
                # `drives_signal` remains in place during the migration.
                triples_out.append(
                    Triple(
                        subject=key[0],
                        predicate="data_flows",
                        object=key[1],
                        source=source,
                        extractor_source=SV_DATAFLOW_SOURCE,
                        layer="slang",
                        attributes={"flow_kind": "intra"},
                    )
                )

    @staticmethod
    def _lhs_subnode(assign_node: Any) -> Optional[Any]:
        """Return the LHS sub-node of an assignment.

        First child whose kind ends in ``IdentifierName`` or
        ``IdentifierSelectName`` is the LHS — pyslang places it before the
        ``=`` / ``<=`` operator token.
        """
        for c in _iter_children(assign_node):
            ck = _kind_str(c)
            if ck.endswith("IdentifierName") or ck.endswith("IdentifierSelectName"):
                return c
        return None

    @staticmethod
    def _collect_idents_skipping(root: Any, skip_node_ids: Set[int]) -> List[str]:
        """Collect every value-reference identifier in *root*'s subtree.

        Identifiers nested inside any node whose ``id()`` is in
        *skip_node_ids* are dropped — used to exclude LHS base names of
        assignment statements from the RHS pool.
        Function-call callees (first IdentifierName child of an
        ``InvocationExpression``) are also skipped.
        """
        out: List[str] = []

        def visit(node: Any) -> None:
            if id(node) in skip_node_ids:
                return
            k = _kind_str(node)
            if k.endswith("IdentifierName"):
                for child in _iter_children(node):
                    if _is_identifier_token(child):
                        txt = _token_text(child)
                        if txt:
                            out.append(txt)
                        break
                return
            if k.endswith("IdentifierSelectName"):
                saw_base = False
                for child in _iter_children(node):
                    if not saw_base and _is_identifier_token(child):
                        txt = _token_text(child)
                        if txt:
                            out.append(txt)
                        saw_base = True
                        continue
                    visit(child)
                return
            if _is_invocation(node):
                seen_callee = False
                for child in _iter_children(node):
                    ck = _kind_str(child)
                    if not seen_callee and ck.endswith("IdentifierName"):
                        seen_callee = True
                        continue
                    visit(child)
                return
            for child in _iter_children(node):
                visit(child)

        visit(root)
        return out

    @staticmethod
    def _make_process_entity(
        name: str, kind_label: str, mod_name: str, source: str,
    ) -> Entity:
        return Entity(
            name=name,
            type="Process",
            sources=[source] if source else [],
            extractor_source=[SV_DATAFLOW_SOURCE],
            layer=SV_DATAFLOW_SOURCE,
        )
