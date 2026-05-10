# @summary
# V2 dataflow integration driver — Wave 2 / track D.
#
# Runs the three Wave 1 walkers (V2DataflowWalker / SVStatementDecomposer /
# sv_xref_resolver) in concert against each pyslang module + process,
# emits all of their AST-layer entities, and additionally bridges
# track-B Condition / Assignment-stub nodes onto the track-A Operator /
# Literal / Index roots that share the same source text within the same
# Process. Bridge edges use the schema-defined predicates: ``operand``
# (Condition → Operator root), ``lhs`` / ``rhs`` (Assignment → expression
# root), ``selector`` (CaseStatement → root), ``case_value`` (Branch →
# root). The bridge edges are additive — the original Condition / stub
# nodes remain so consumers that were already querying their ``text``
# attribute keep working.
#
# Process IDs match v1's `<module>.<kind>_<idx>` naming exactly so v1's
# `drives_signal` / `assigned_in` triples and v2's AST internals share
# one Process node.
#
# Exports: V2IntegrationDriver, V2_INTEGRATION_SOURCE
# Deps: pyslang (hard), kgweave.knowledge_graph.common,
#       kgweave.knowledge_graph.extraction.{sv_v2_walker,
#       sv_dataflow_v2_statements}
# @end-summary
"""V2 integration driver.

Tied to the Wave-2 / track-D scope described in the v2 dataflow schema doc
(``docs/v2_dataflow_schema.md`` § "Schema migration" and "Layering").

The driver is gated by ``KGConfig.enable_ast_decomposition`` — callers who
do not want the AST layer simply do not invoke this extractor. The driver
emits **only** the additive ``layer="ast"`` content; v1's
``SVDataflowExtractor`` continues to emit ``Process`` /
``drives_signal`` / ``assigned_in`` separately, and the two outputs share
the same canonical Process IDs.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import pyslang as _ps  # noqa: E402 — hard dep matches the rest of the package

from kgweave.knowledge_graph.common import Entity, ExtractionResult, Triple

from kgweave.knowledge_graph.extraction.sv_v2_walker import (
    V2DataflowWalker,
    V2_WALKER_SOURCE,
)
from kgweave.knowledge_graph.extraction.sv_dataflow_v2_statements import (
    SVStatementDecomposer,
    SV_V2_STMT_SOURCE,
)


__all__ = ["V2IntegrationDriver", "V2_INTEGRATION_SOURCE"]


logger = logging.getLogger(
    "kgweave.knowledge_graph.extraction.sv_v2_integration"
)

V2_INTEGRATION_SOURCE = "sv_v2_integration"
_AST_LAYER = "ast"


class V2IntegrationDriver:
    """Drives the three Wave-1 walkers + emits Wave-2 bridge edges.

    Construction takes the same ``known_module_signals`` table v1 / track A
    use, so reference resolution can decide whether a name is a real
    module-scope signal.
    """

    name: str = V2_INTEGRATION_SOURCE

    def __init__(self, known_module_signals: Dict[str, Set[str]]) -> None:
        self._known: Dict[str, Set[str]] = {
            mod: set(sigs) for mod, sigs in (known_module_signals or {}).items()
        }

    # ------------------------------------------------------------------ API

    def extract(self, text: str = "", source: str = "") -> ExtractionResult:
        if not text or not text.strip():
            return ExtractionResult()

        # Run each Wave-1 walker. Each one independently parses the source
        # — they're cheap, so we don't bother sharing the SyntaxTree.
        walker = V2DataflowWalker(known_module_signals=self._known)
        a_res = walker.extract(text=text, source=source)
        text_to_root = dict(walker.text_to_root)

        b_res = SVStatementDecomposer().extract(text=text, source=source)

        # Track A's V2DataflowWalker only resolves identifiers as
        # qualified-name strings. For the bridge step, we also want to
        # accept plain identifiers as bridge targets (e.g. an Assignment
        # whose RHS is just `a`). We supplement text_to_root with
        # `(process_id, signal_name) -> module.signal_name` for every
        # known module signal.
        for mod, sigs in self._known.items():
            for sig in sigs:
                # The process is per-process, but we don't know which
                # process maps to a given (mod, sig); we fall back later
                # by stripping the process prefix.
                pass

        bridge_triples = self._emit_bridges(b_res.entities, b_res.triples,
                                            text_to_root, source=source)

        all_entities: List[Entity] = list(a_res.entities) + list(b_res.entities)
        all_triples: List[Triple] = (
            list(a_res.triples) + list(b_res.triples) + bridge_triples
        )
        return ExtractionResult(entities=all_entities, triples=all_triples)

    # -------------------------------------------------------------- Bridge

    def _emit_bridges(
        self,
        b_entities: List[Entity],
        b_triples: List[Triple],
        text_to_root: Dict[Tuple[str, str], str],
        source: str,
    ) -> List[Triple]:
        """Emit additive bridge edges from track-B stubs to track-A roots.

        Strategy: for every track-B Condition / Assignment stub-pair, look
        up the canonical root by ``(process_id, stripped_text)``. The
        process_id is recoverable from the entity name's
        ``<module>.<kind>_<idx>.<rest>`` prefix. If the text doesn't match
        any track-A root, we do *not* emit a bridge — the stub still
        carries a ``text`` attribute, and the audit consumer can still
        recover the expression. This keeps the bridge edge silently
        additive when shapes diverge (e.g. plain-identifier RHS).
        """
        # Index B entities by name for quick lookup of types/text.
        b_by_name: Dict[str, Entity] = {e.name: e for e in b_entities}

        # Index B triples by (subject, predicate) so we know which stub a
        # bridge belongs to. Track B emits, e.g. Assignment --lhs--> stub
        # and the stub itself carries the text. We follow these forward.
        bridge_triples: List[Triple] = []

        # Helper: bridge predicate to use for each stub-class.
        # The Condition stub uses `operand` to point at its root expression
        # (matching the Operator → expression-node operand pattern). The
        # Assignment stub LHS/RHS reuses `lhs` / `rhs` for the root
        # connection, which is the predicate the schema doc specifies on
        # Assignment edges.
        for triple in b_triples:
            stub_id = triple.object
            stub = b_by_name.get(stub_id)
            if stub is None:
                continue
            pred = triple.predicate
            stub_type = getattr(stub, "type", None)

            # Identify stubs the integration layer should bridge. The
            # statement walker materialises Condition stubs at five sites:
            # if-predicate, case-selector, case_value, assignment LHS,
            # assignment RHS. The triple predicate disambiguates them.
            if pred not in {"condition_of", "selector", "case_value",
                            "lhs", "rhs"}:
                continue

            # Must be a stub-shaped node — Condition with a 'text' attribute.
            if stub_type != "Condition":
                continue
            stub_text = (stub.attributes or {}).get("text", "")
            if not isinstance(stub_text, str):
                continue
            stub_text = stub_text.strip()
            if not stub_text:
                continue

            # Recover process_id from the stub's name. The statement
            # walker mints names of the form
            # ``<module>.<kind>_<idx>.<hash>{.cond,.lhs,.rhs,.selector,
            # .case_value}``. The process_id is the first three '.'-sep
            # segments — but only if the second contains the process kind
            # underscore-counter. Use a heuristic: take the first two
            # segments joined by '.'.
            process_id = _process_id_of(stub_id)
            if process_id is None:
                continue

            root_name = text_to_root.get((process_id, stub_text))

            # Fallbacks: try without trailing whitespace differences,
            # and try collapsing internal whitespace.
            if root_name is None:
                # Try looking up with normalised whitespace.
                norm = _norm_ws(stub_text)
                for (pid, txt), rn in text_to_root.items():
                    if pid == process_id and _norm_ws(txt) == norm:
                        root_name = rn
                        break

            if root_name is None:
                # Try plain-identifier fallback: stub text is just `sig`
                # → bridge to qualified module signal `<module>.<sig>`.
                if _is_plain_identifier(stub_text):
                    mod = process_id.rsplit(".", 1)[0] if "." in process_id else ""
                    if mod and stub_text in self._known.get(mod, set()):
                        root_name = f"{mod}.{stub_text}"

            if root_name is None or root_name == stub_id:
                continue

            # Emit the bridge. Use `operand` for Condition→expression
            # bridges; reuse the original predicate name for Assignment
            # lhs/rhs/selector/case_value so consumers querying by edge
            # name see the canonical predicate hooked directly to the
            # expression root.
            bridge_pred = "operand" if pred in {"condition_of"} else pred

            # We emit from the *stub* (or, for the assignment / case
            # cases, from the parent of the stub) to the resolved root.
            # In all cases we emit from the stub — adding a connecting
            # edge so a graph walker doing condition→operator can take
            # one extra hop without changing existing consumers.
            attrs: Dict[str, Any] = {"bridge": True, "stub_pred": pred}
            bridge_triples.append(
                Triple(
                    subject=stub_id,
                    predicate=bridge_pred,
                    object=root_name,
                    source=source,
                    extractor_source=V2_INTEGRATION_SOURCE,
                    layer=_AST_LAYER,
                    attributes=attrs,
                )
            )

        return bridge_triples


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PROCESS_KIND_TOKENS = (
    "always_ff_", "always_comb_", "always_latch_", "always_", "assign_",
    "initial_", "final_",
)


def _process_id_of(entity_name: str) -> Optional[str]:
    """Recover the canonical process id (``<module>.<kind>_<idx>``) from
    an entity name minted by tracks A/B.

    Track A uses ``<module>.<kind>_<idx>.<hash>`` and Track B mints
    ``<module>.<kind>_<idx>.<hash>{.cond,.lhs,.rhs,.if,.case,.loop,
    .selector,.case_value,.expr,.assign,.br}``. We strip from the right
    until we hit a segment whose tail is ``<kind>_<n>``.
    """
    parts = entity_name.split(".")
    for i in range(len(parts) - 1, 0, -1):
        seg = parts[i]
        for tok in _PROCESS_KIND_TOKENS:
            if seg.startswith(tok) and seg[len(tok):].isdigit():
                return ".".join(parts[: i + 1])
    return None


def _is_plain_identifier(text: str) -> bool:
    if not text:
        return False
    if not (text[0].isalpha() or text[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in text)


def _norm_ws(text: str) -> str:
    return " ".join(text.split())
