# @summary
# Typed data contracts for the KG subsystem.
# Exports: EntityDescription, Entity, Triple, ExtractionResult
# Deps: dataclasses, typing
# @end-summary
"""Typed data contracts for the KG subsystem.

All types are pure dataclasses with no business logic — they serve as the
shared interchange format between extractors, backends, and query layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple


__all__ = [
    "EntityDescription",
    "Entity",
    "Triple",
    "ExtractionResult",
    "LayerDiff",
]


@dataclass
class EntityDescription:
    """A single textual mention of an entity in a source document.

    Attributes:
        text: The sentence or passage containing the mention.
        source: Document path or URI where the mention was found.
        chunk_id: Originating chunk identifier within the document.
    """

    text: str
    source: str
    chunk_id: str


@dataclass
class Entity:
    """A node in the knowledge graph.

    Attributes:
        name: Canonical (first-seen) name for the entity.
        type: Node type as defined in the KG schema (e.g. ``RTL_Module``).
        sources: List of document paths that mention this entity.
        mention_count: Number of times this entity has been observed.
        aliases: Alternative names or acronyms that resolve to this entity.
        raw_mentions: Ordered list of raw textual mentions collected so far.
        current_summary: LLM-generated condensed description of the entity.
        extractor_source: Names of the extractors that produced this entity.
    """

    name: str
    type: str
    sources: List[str] = field(default_factory=list)
    mention_count: int = 1
    aliases: List[str] = field(default_factory=list)
    raw_mentions: List[EntityDescription] = field(default_factory=list)
    current_summary: str = ""
    extractor_source: List[str] = field(default_factory=list)
    # Stage-1 audit/recall split (REQ: SW_Test precision vs test-completeness recall):
    # ``is_test`` flags whether this entity should count as a runnable test in the
    # test-completeness view. ``None`` means "not applicable / not yet evaluated"
    # — the default for non-test-like types. Producers of test-like entities
    # (e.g. SW_Test extractor) set this explicitly to ``True`` (real test) or
    # ``False`` (heuristic match that should be excluded from audit reporting,
    # e.g. ``crt0.c`` runtime files).
    is_test: Optional[bool] = None
    # Source layer that originally introduced this entity (e.g. ``"slang"``,
    # ``"sdc"``, ``"markdown_doc"``). Used by ``backend.entities_by_layer`` /
    # ``backend.diff_layers`` for per-source slicing. ``None`` means
    # unspecified — the entity's layer was not declared by the producing
    # extractor. Multiple layers may reference the same canonical node;
    # only the *introducing* layer is recorded here.
    layer: Optional[str] = None
    # Direction for ``Port`` entities — one of ``"input"``, ``"output"``,
    # ``"inout"``, or ``None`` (irrelevant / unknown). Populated by the
    # slang extractor from the elaborated port symbol's ``direction`` and
    # (best-effort) by the parser extractor from the port-declaration
    # syntax. ``None`` for non-Port entities and for ports whose direction
    # could not be classified (e.g. ``ref`` arguments).
    port_direction: Optional[Literal["input", "output", "inout"]] = None
    # Free-form structured metadata that is NOT a name, NOT a description,
    # and NOT a source attribution. Used by extractors to carry typed
    # payloads (e.g. ``{"kind": "Add"}`` for an Operator, or
    # ``{"branch_path": ["m.always_0.if.br", ...]}`` for a Branch) without
    # abusing string fields like ``aliases`` or ``current_summary``.
    # Backend treats this as opaque payload — entries are merged into the
    # node data dict but NEVER routed through the alias-resolution index.
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Triple:
    """A directed relationship triple: subject → predicate → object.

    Attributes:
        subject: Canonical name of the source entity.
        predicate: Edge type label (e.g. ``instantiates``, ``specified_by``).
        object: Canonical name of the target entity.
        source: Document path or URI from which this triple was extracted.
        weight: Mention-frequency weight (accumulates on duplicate edges).
        extractor_source: Name of the extractor that produced this triple.
        confidence: Trust score in [0, 1] reflecting extractor reliability.
            Distinct from ``weight``: weight measures how often a relation
            was observed; confidence measures how trustworthy each
            observation is. Combined across duplicate triples via the
            noisy-OR rule in ``extractor_priors.combine_confidence``.
        evidence_span: The original source-text snippet that supports this
            triple (e.g. the sentence the LLM extracted it from). Empty for
            extractors with no natural evidence span (e.g. AST-derived).
        chunk_id: Originating chunk identifier within the source document.
        extracted_at: UTC timestamp when this triple was first produced.
    """

    subject: str
    predicate: str
    object: str
    source: str = ""
    weight: float = 1.0
    extractor_source: str = ""
    confidence: float = 1.0
    evidence_span: str = ""
    chunk_id: str = ""
    extracted_at: Optional[datetime] = None
    # Symbolic bit-slice text on the LHS / RHS base symbol (e.g. ``"[31:24]"``,
    # ``"[ADDR_W-1:0]"``, ``"[5]"``). ``None`` means whole-signal (no slice).
    # Currently populated only by the SV connectivity dataflow walker for the
    # ``reads`` predicate; other extractors leave them as ``None``. Symbolic
    # only — parameter expressions are *not* resolved (Phase-1 scope).
    lhs_slice: Optional[str] = None
    rhs_slice: Optional[str] = None
    # Stage-1 audit/recall split: coarse trust tier orthogonal to the numeric
    # ``confidence`` score above. ``"high"`` = explicit symbol/DIF match;
    # ``"medium"`` = filename/substring heuristic; ``"low"`` = weak heuristic.
    # Defaults to ``"high"`` so existing extractors emit unchanged metadata.
    confidence_tier: Literal["high", "medium", "low"] = "high"
    # ``resolved=False`` marks triples whose object was not found in the
    # entity table (dangling reference). Audit views can filter on this to
    # distinguish "real" edges from speculative ones while the recall view
    # keeps everything.
    resolved: bool = True
    # Source layer that produced this triple (e.g. ``"slang"``, ``"sdc"``,
    # ``"ipxact"``). When ``None`` and ``extractor_source`` is set, the
    # backend falls back to ``extractor_source`` for backwards compat.
    # Used by ``backend.subgraph_by_layer`` / ``triples_by_layer`` /
    # ``diff_layers`` for per-source slicing.
    layer: Optional[str] = None
    # Free-form structured metadata for edges, parallel to ``Entity.attributes``.
    # Backend merges this into edge data dict but does NOT treat any entry
    # as a routing/resolution key. Use for typed edge payloads such as
    # ``{"operand_index": 0}`` rather than abusing ``evidence_span``.
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Aggregated output from a single extractor run.

    Attributes:
        entities: List of extracted entities.
        triples: List of extracted relationship triples.
        descriptions: Per-entity mention lists keyed by canonical entity name.
    """

    entities: List[Entity] = field(default_factory=list)
    triples: List[Triple] = field(default_factory=list)
    descriptions: Dict[str, List[EntityDescription]] = field(default_factory=dict)


@dataclass
class LayerDiff:
    """Diff between two layers' assertions over the entity space.

    Identity is by canonical entity name (post-resolve). For ``in_both``
    entities, ``conflicting_attrs`` lists per-attribute disagreements
    discovered between the two layers' views.

    Attributes:
        layer_a: First layer name compared.
        layer_b: Second layer name compared.
        only_in_a: Canonical names present only under ``layer_a``.
        only_in_b: Canonical names present only under ``layer_b``.
        in_both: Canonical names asserted by both layers.
        conflicting_attrs: ``(entity_name, attr_name, value_in_a, value_in_b)``
            tuples for attributes that disagree across the two layers.
    """

    layer_a: str
    layer_b: str
    only_in_a: List[str] = field(default_factory=list)
    only_in_b: List[str] = field(default_factory=list)
    in_both: List[str] = field(default_factory=list)
    conflicting_attrs: List[Tuple[str, str, Any, Any]] = field(default_factory=list)
