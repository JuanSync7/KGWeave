# @summary
# NetworkX-based concrete implementation of GraphStorageBackend.
# Exports: NetworkXBackend
# Deps: networkx, orjson, src.knowledge_graph.backend, src.knowledge_graph.common.schemas
# Notable: MultiDiGraph keyed by predicate; per-instance evidence accumulation.
# @end-summary
"""NetworkX-based graph storage backend.

Implements :class:`GraphStorageBackend` using an in-memory
``nx.MultiDiGraph``. Edges are keyed by predicate so that parallel
predicates between the same pair of nodes (e.g. ``is_a`` and
``subset_of`` between A and B) are preserved as distinct edges.

Per-edge evidence accumulates into an ``evidences`` list (each entry a
dict with ``evidence_span``, ``chunk_id``, ``extracted_at``, ``source``)
so that repeated upserts of the same triple from different sources
preserve every observation rather than overwriting the first.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx
import orjson

from kgweave.knowledge_graph.backend import GraphStorageBackend, MergeReport, RemovalStats
from kgweave.knowledge_graph.common import (
    Entity,
    EntityDescription,
    LayerDiff,
    Triple,
)

__all__ = ["NetworkXBackend"]

logger = logging.getLogger(__name__)

# Default token budget for accumulated entity descriptions.
_DEFAULT_DESCRIPTION_TOKEN_BUDGET = 600


class NetworkXBackend(GraphStorageBackend):
    """NetworkX ``DiGraph``-backed knowledge-graph storage.

    Maintains two auxiliary indices for entity resolution:

    * ``_aliases``     — maps surface-form aliases to canonical node names.
    * ``_case_index``  — maps lowercased names to canonical (first-seen) form.

    Persistence uses ``orjson`` + ``nx.node_link_data`` so that saved files
    remain readable by the legacy ``KnowledgeGraphBuilder.load()`` path.
    """

    def __init__(
        self,
        description_token_budget: int = _DEFAULT_DESCRIPTION_TOKEN_BUDGET,
    ) -> None:
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self._aliases: Dict[str, str] = {}
        self._case_index: Dict[str, str] = {}
        self._description_token_budget = description_token_budget

    # ------------------------------------------------------------------
    # Entity resolution (migrated from KnowledgeGraphBuilder._resolve)
    # ------------------------------------------------------------------

    def _resolve(self, term: str) -> str:
        """Resolve an alias/acronym then deduplicate by case.

        Priority: acronym alias -> case-insensitive existing node -> original.
        First-seen form becomes canonical (preserves original casing).
        """
        # Acronym / alias expansion first
        term = self._aliases.get(term, term)
        # Case-insensitive dedup: reuse existing canonical form
        lower = term.lower()
        if lower in self._case_index:
            return self._case_index[lower]
        # First time seeing this (case-insensitive) — register it
        self._case_index[lower] = term
        return term

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_node(
        self,
        name: str,
        type: str,
        source: str,
        aliases: Optional[List[str]] = None,
        layer: Optional[str] = None,
        is_test: Optional[bool] = None,
        port_direction: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Upsert a single entity node with alias/case dedup.

        ``layer`` is the source-of-origin tag (e.g. ``"slang"``, ``"sdc"``).
        Sticky on first set: subsequent upserts of the same node do not
        overwrite the introducing layer.
        """
        canonical = self._resolve(name)

        if self.graph.has_node(canonical):
            data = self.graph.nodes[canonical]
            # A node may have been auto-created by add_edge before we ever
            # saw it as an entity, in which case it lacks the entity attrs.
            # An explicit Entity upsert always wins over the placeholder
            # ``"concept"`` type left by ``add_edge``, but does not clobber
            # a real type set by an earlier extractor (last-write semantics
            # apply only to the placeholder case).
            existing_type = data.get("type")
            if existing_type is None or existing_type == "concept":
                data["type"] = type
            data.setdefault("sources", [])
            data.setdefault("aliases", [])
            data["mention_count"] = data.get("mention_count", 0) + 1
            # Layer is sticky to the introducing extractor — only set if
            # not already present (preserves "originally introduced by"
            # semantics even when later layers reference the same node).
            if layer is not None and not data.get("layer"):
                data["layer"] = layer
            # ``is_test`` is non-sticky: an explicit upsert always overrides
            # because it carries the producer's freshest classification.
            # ``None`` means "not provided, leave as is".
            if is_test is not None:
                data["is_test"] = is_test
            elif "is_test" not in data:
                data["is_test"] = None
            # ``port_direction`` is sticky-by-explicit-set: an explicit value
            # always wins; ``None`` means "not provided by this caller", do
            # not erase a prior value. Default to ``None`` only when the
            # attribute has never been set.
            if port_direction is not None:
                data["port_direction"] = port_direction
            elif "port_direction" not in data:
                data["port_direction"] = None
            if source and source not in data["sources"]:
                data["sources"].append(source)
            if aliases:
                for a in aliases:
                    if a not in data["aliases"]:
                        data["aliases"].append(a)
                    # Register alias in the alias index
                    self._aliases[a] = canonical
                    self._case_index[a.lower()] = canonical
            # Merge free-form attributes (later writes win for the same key).
            # Explicit dict update — NOT routed through the alias index.
            if attributes:
                data.setdefault("attributes", {}).update(attributes)
        else:
            self.graph.add_node(
                canonical,
                type=type,
                sources=[source] if source else [],
                mention_count=1,
                aliases=list(aliases) if aliases else [],
                layer=layer,
                is_test=is_test,
                port_direction=port_direction,
                attributes=dict(attributes) if attributes else {},
            )
            # Register aliases
            if aliases:
                for a in aliases:
                    self._aliases[a] = canonical
                    self._case_index[a.lower()] = canonical

    def add_edge(
        self,
        subject: str,
        object: str,
        relation: str,
        source: str,
        weight: float = 1.0,
        confidence: float = 1.0,
        evidence_span: str = "",
        chunk_id: str = "",
        extracted_at=None,
        lhs_slice=None,
        rhs_slice=None,
        layer: Optional[str] = None,
        extractor_source: str = "",
        confidence_tier: str = "high",
        resolved: bool = True,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Upsert a directed edge keyed by predicate.

        The backend uses a ``MultiDiGraph`` keyed by predicate (relation),
        so parallel edges with different predicates between the same pair
        of nodes coexist without collapsing.

        On duplicate edges (same subject/object/predicate):
            * ``weight`` accumulates (mention frequency).
            * ``confidence`` combines via noisy-OR (agreement bump).
            * ``evidence_span`` / ``chunk_id`` / ``extracted_at`` are
              appended to ``evidences`` (a list of per-observation dicts)
              so every observation is preserved for later citation.
            * ``source`` is appended to the ``sources`` list.
        """
        # Local import to avoid circular dependency at module load time.
        from kgweave.knowledge_graph.common.extractor_priors import (
            combine_confidence,
        )

        subj_c = self._resolve(subject)
        obj_c = self._resolve(object)

        # Silently drop self-edges
        if subj_c == obj_c:
            return

        # Ensure both endpoint nodes exist with proper entity attrs before
        # we add the edge. NetworkX's add_edge would otherwise auto-create
        # bare nodes lacking the ``sources``/``mention_count``/``aliases``
        # attrs that downstream consumers (legend, tooltip, retrieval)
        # rely on. Propagate the triple's source to each endpoint so nodes
        # introduced solely via edges still surface their origin.
        for endpoint in (subj_c, obj_c):
            if self.graph.has_node(endpoint):
                node_data = self.graph.nodes[endpoint]
                node_data.setdefault("type", "concept")
                node_data.setdefault("sources", [])
                node_data.setdefault("aliases", [])
                node_data.setdefault("mention_count", 1)
                if source and source not in node_data["sources"]:
                    node_data["sources"].append(source)
            else:
                self.graph.add_node(
                    endpoint,
                    type="concept",
                    sources=[source] if source else [],
                    mention_count=1,
                    aliases=[],
                )

        # Layer fallback: if not explicitly passed, fall back to
        # ``extractor_source`` for backwards compat with extractors that
        # populate only the legacy field.
        effective_layer = layer if layer is not None else (extractor_source or None)

        # MultiDiGraph: key edges by predicate so that (A, is_a, B) and
        # (A, subset_of, B) can coexist without one shadowing the other.
        # Slice attrs are only meaningful for ``reads`` edges (intra-module
        # signal-level dataflow with bit-range refinement). Other predicates
        # ignore them so edge-data shape stays unchanged.
        slice_relevant = relation == "reads"
        new_evidence = {
            "evidence_span": evidence_span,
            "chunk_id": chunk_id,
            "extracted_at": extracted_at,
            "source": source,
        }
        if slice_relevant:
            new_evidence["lhs_slice"] = lhs_slice
            new_evidence["rhs_slice"] = rhs_slice

        if self.graph.has_edge(subj_c, obj_c, key=relation):
            edge_data = self.graph[subj_c][obj_c][relation]
            edge_data["weight"] = edge_data.get("weight", 0.0) + weight
            # Layer is sticky to the first observation — preserve original
            # source-of-origin even when other layers re-assert the edge.
            if effective_layer is not None and not edge_data.get("layer"):
                edge_data["layer"] = effective_layer
            existing_conf = edge_data.get("confidence", 1.0)
            edge_data["confidence"] = combine_confidence(existing_conf, confidence)
            # Confidence tier: keep the strongest tier observed across
            # duplicates. Resolved is sticky-True — any resolved observation
            # clears prior unresolved status (we now have a real referent).
            _tier_rank = {"high": 3, "medium": 2, "low": 1}
            existing_tier = edge_data.get("confidence_tier", "high")
            if _tier_rank.get(confidence_tier, 0) > _tier_rank.get(existing_tier, 0):
                edge_data["confidence_tier"] = confidence_tier
            if resolved:
                edge_data["resolved"] = True
            else:
                edge_data.setdefault("resolved", False)
            if source and source not in edge_data.get("sources", []):
                edge_data.setdefault("sources", []).append(source)
            # Accumulate evidence — append for ``reads`` edges whenever any
            # slice/evidence detail is present (so per-observation slices
            # are preserved even if evidence_span repeats), and otherwise
            # only when at least one of the legacy evidence fields differs
            # from the empty default.
            should_append = any(v for v in (evidence_span, chunk_id, extracted_at))
            if slice_relevant and (lhs_slice is not None or rhs_slice is not None):
                should_append = True
            if should_append:
                edge_data.setdefault("evidences", []).append(new_evidence)
                # Surface the latest observation on the scalar fields so
                # legacy callers that read edge["evidence_span"] still
                # work — they simply now see the most recent observation.
                if evidence_span:
                    edge_data["evidence_span"] = evidence_span
                if chunk_id:
                    edge_data["chunk_id"] = chunk_id
                if extracted_at is not None:
                    edge_data["extracted_at"] = extracted_at
            # Merge free-form edge attributes (later writes win per-key).
            if attributes:
                edge_data.setdefault("attributes", {}).update(attributes)
            if slice_relevant:
                # Top-level slice = consensus across all observations; if
                # any observation disagrees, surface ``None`` ("mixed").
                pairs = {
                    (ev.get("lhs_slice"), ev.get("rhs_slice"))
                    for ev in edge_data.get("evidences", [])
                }
                if len(pairs) == 1:
                    only = next(iter(pairs))
                    edge_data["lhs_slice"] = only[0]
                    edge_data["rhs_slice"] = only[1]
                else:
                    edge_data["lhs_slice"] = None
                    edge_data["rhs_slice"] = None
        else:
            evidences = []
            should_append = any(v for v in (evidence_span, chunk_id, extracted_at))
            if slice_relevant and (lhs_slice is not None or rhs_slice is not None):
                should_append = True
            if should_append:
                evidences.append(new_evidence)
            extra: dict = {}
            if slice_relevant:
                extra["lhs_slice"] = lhs_slice
                extra["rhs_slice"] = rhs_slice
            self.graph.add_edge(
                subj_c,
                obj_c,
                key=relation,
                relation=relation,
                weight=weight,
                confidence=confidence,
                evidence_span=evidence_span,
                chunk_id=chunk_id,
                extracted_at=extracted_at,
                sources=[source] if source else [],
                evidences=evidences,
                layer=effective_layer,
                confidence_tier=confidence_tier,
                resolved=resolved,
                attributes=dict(attributes) if attributes else {},
                **extra,
            )

    def upsert_entities(self, entities: List[Entity]) -> None:
        """Batch upsert entities via ``add_node``."""
        for ent in entities:
            # Fall back to first ``extractor_source`` when ``layer`` is unset
            # — preserves source-of-origin for legacy extractors that only
            # populate ``extractor_source`` on Entity.
            ent_layer = ent.layer
            if ent_layer is None and ent.extractor_source:
                ent_layer = ent.extractor_source[0]
            self.add_node(
                name=ent.name,
                type=ent.type,
                source=ent.sources[0] if ent.sources else "",
                aliases=ent.aliases or None,
                layer=ent_layer,
                is_test=getattr(ent, "is_test", None),
                port_direction=getattr(ent, "port_direction", None),
                attributes=getattr(ent, "attributes", None) or None,
            )
            # Merge remaining sources beyond the first
            canonical = self._resolve(ent.name)
            if self.graph.has_node(canonical):
                node_data = self.graph.nodes[canonical]
                for src in ent.sources[1:]:
                    if src and src not in node_data["sources"]:
                        node_data["sources"].append(src)

    def upsert_triples(self, triples: List[Triple]) -> None:
        """Batch upsert triples via ``add_edge``.

        Confidence resolution rule: when ``extractor_source`` is non-empty,
        the per-extractor prior (see ``extractor_priors``) overrides the
        ``Triple.confidence`` field. This keeps extractor implementations
        free of confidence bookkeeping — they only declare which extractor
        they are, and the backend assigns the trust score.

        Layer fallback: when ``Triple.layer`` is ``None`` but
        ``Triple.extractor_source`` is set, the backend uses the
        ``extractor_source`` value as the edge's layer. This preserves
        source-of-origin tracking for legacy extractors that have not yet
        opted in to populating the explicit ``layer`` field.
        """
        from kgweave.knowledge_graph.common.extractor_priors import (
            confidence_for,
        )

        for t in triples:
            confidence = (
                confidence_for(t.extractor_source)
                if t.extractor_source
                else t.confidence
            )
            self.add_edge(
                subject=t.subject,
                object=t.object,
                relation=t.predicate,
                source=t.source,
                weight=t.weight,
                confidence=confidence,
                evidence_span=t.evidence_span,
                chunk_id=t.chunk_id,
                extracted_at=t.extracted_at,
                lhs_slice=getattr(t, "lhs_slice", None),
                rhs_slice=getattr(t, "rhs_slice", None),
                layer=getattr(t, "layer", None),
                extractor_source=t.extractor_source,
                confidence_tier=getattr(t, "confidence_tier", "high"),
                resolved=getattr(t, "resolved", True),
                attributes=getattr(t, "attributes", None) or None,
            )

    def upsert_descriptions(
        self, descriptions: Dict[str, List[EntityDescription]]
    ) -> None:
        """Append textual mentions to entity records, respecting token budget.

        Per REQ-KG-400: new mentions are appended with source attribution.
        When the accumulated token count exceeds ``description_token_budget``,
        the oldest mentions are dropped so the most recent ones fit within
        the budget.
        """
        for name, desc_list in descriptions.items():
            canonical = self._resolve(name)
            if not self.graph.has_node(canonical):
                # Entity not yet in graph — skip silently
                logger.debug(
                    "Skipping descriptions for unknown entity %r", canonical
                )
                continue

            node_data = self.graph.nodes[canonical]
            raw: List[Dict[str, str]] = node_data.setdefault("raw_mentions", [])

            for desc in desc_list:
                raw.append(
                    {
                        "text": desc.text,
                        "source": desc.source,
                        "chunk_id": desc.chunk_id,
                    }
                )

            # Token-budget enforcement: approximate tokens = word count
            self._enforce_token_budget(raw)

    def _enforce_token_budget(self, mentions: List[Dict[str, str]]) -> None:
        """Trim oldest mentions so total tokens stay within budget."""
        budget = self._description_token_budget
        # Walk from newest to oldest, accumulating tokens
        kept: List[Dict[str, str]] = []
        total_tokens = 0
        for mention in reversed(mentions):
            tokens = len(mention["text"].split())
            if total_tokens + tokens > budget and kept:
                # Adding this mention would exceed the budget
                break
            kept.append(mention)
            total_tokens += tokens

        # Restore chronological order (oldest first)
        kept.reverse()
        mentions[:] = kept

    def remove_by_source(self, source_key: str) -> RemovalStats:
        """Remove or prune all graph data associated with *source_key*.

        Entities whose ``sources`` list contains *source_key* as the only
        source are deleted entirely.  Entities that also appear in other
        sources have *source_key* pruned from their ``sources`` list — the
        node itself survives.  All edges whose ``sources`` list contains
        *source_key* are removed unconditionally.

        Args:
            source_key: Document path or URI whose data should be removed.

        Returns:
            ``RemovalStats`` describing how many entities were removed, pruned,
            and how many triples were deleted.
        """
        stats = RemovalStats(source_key=source_key)
        nodes_to_delete: List[str] = []

        # --- Pass 1: classify nodes ---
        for node, data in list(self.graph.nodes(data=True)):
            sources: List[str] = data.get("sources", [])
            if source_key not in sources:
                continue
            if len(sources) == 1:
                # source_key is the sole source — mark for deletion
                nodes_to_delete.append(node)
                stats.entities_removed += 1
            else:
                # Entity lives in other sources too — prune only this source
                data["sources"] = [s for s in sources if s != source_key]
                stats.entities_pruned += 1

        # --- Pass 2: remove edges that belong to source_key ---
        edges_to_remove = [
            (u, v, k)
            for u, v, k, data in self.graph.edges(keys=True, data=True)
            if source_key in data.get("sources", [])
        ]
        for u, v, k in edges_to_remove:
            self.graph.remove_edge(u, v, key=k)
            stats.triples_removed += 1

        # --- Pass 3: delete marked nodes and clean up indices ---
        for node in nodes_to_delete:
            # Clean _case_index entries that point to this node
            stale_case_keys = [k for k, v in self._case_index.items() if v == node]
            for k in stale_case_keys:
                del self._case_index[k]
            # Clean _aliases entries that point to this node
            stale_alias_keys = [k for k, v in self._aliases.items() if v == node]
            for k in stale_alias_keys:
                del self._aliases[k]
            self.graph.remove_node(node)

        logger.debug(
            "remove_by_source(%r): removed=%d pruned=%d triples=%d",
            source_key,
            stats.entities_removed,
            stats.entities_pruned,
            stats.triples_removed,
        )
        return stats

    def merge_entities(self, canonical: str, duplicate: str) -> None:
        """Merge *duplicate* into *canonical*, then delete the duplicate node.

        All edges referencing *duplicate* as subject or object are redirected
        to *canonical*.  Aliases, mention counts, ``raw_mentions``, and
        ``sources`` from *duplicate* are merged into *canonical*.

        Args:
            canonical: Canonical name of the surviving entity.
            duplicate: Canonical name of the entity to absorb and delete.
        """
        if not self.graph.has_node(canonical):
            logger.warning(
                "merge_entities: canonical node %r does not exist — aborting", canonical
            )
            return
        if not self.graph.has_node(duplicate):
            # Duplicate already gone — nothing to do
            logger.debug(
                "merge_entities: duplicate node %r not found — skipping", duplicate
            )
            return

        can_data = self.graph.nodes[canonical]
        dup_data = self.graph.nodes[duplicate]

        # --- Transfer outgoing edges: duplicate → X  becomes  canonical → X ---
        for _, target, key, edge_data in list(
            self.graph.out_edges(duplicate, keys=True, data=True)
        ):
            if target == canonical:
                # Would create a self-loop — skip
                continue
            relation = edge_data.get("relation", key)
            if self.graph.has_edge(canonical, target, key=relation):
                self.graph[canonical][target][relation]["weight"] = (
                    self.graph[canonical][target][relation].get("weight", 1.0)
                    + edge_data.get("weight", 1.0)
                )
            else:
                self.graph.add_edge(
                    canonical,
                    target,
                    key=relation,
                    relation=relation,
                    weight=edge_data.get("weight", 1.0),
                    sources=list(edge_data.get("sources", [])),
                    evidences=list(edge_data.get("evidences", [])),
                )

        # --- Transfer incoming edges: X → duplicate  becomes  X → canonical ---
        for source_node, _, key, edge_data in list(
            self.graph.in_edges(duplicate, keys=True, data=True)
        ):
            if source_node == canonical:
                # Would create a self-loop — skip
                continue
            relation = edge_data.get("relation", key)
            if self.graph.has_edge(source_node, canonical, key=relation):
                self.graph[source_node][canonical][relation]["weight"] = (
                    self.graph[source_node][canonical][relation].get("weight", 1.0)
                    + edge_data.get("weight", 1.0)
                )
            else:
                self.graph.add_edge(
                    source_node,
                    canonical,
                    key=relation,
                    relation=relation,
                    weight=edge_data.get("weight", 1.0),
                    sources=list(edge_data.get("sources", [])),
                    evidences=list(edge_data.get("evidences", [])),
                )

        # --- Merge aliases: duplicate's name + its aliases → canonical ---
        existing_aliases: List[str] = can_data.setdefault("aliases", [])
        new_aliases: List[str] = [duplicate] + list(dup_data.get("aliases", []))
        for alias in new_aliases:
            if alias not in existing_aliases:
                existing_aliases.append(alias)

        # --- Merge sources ---
        existing_sources: List[str] = can_data.setdefault("sources", [])
        for src in dup_data.get("sources", []):
            if src not in existing_sources:
                existing_sources.append(src)

        # --- Merge mention counts ---
        can_data["mention_count"] = can_data.get("mention_count", 1) + dup_data.get(
            "mention_count", 1
        )

        # --- Merge raw_mentions ---
        can_raw: List[Dict] = can_data.setdefault("raw_mentions", [])
        can_raw.extend(dup_data.get("raw_mentions", []))

        # --- Update _case_index: duplicate's lowercase name → canonical ---
        self._case_index[duplicate.lower()] = canonical

        # --- Update _aliases: duplicate's aliases → canonical ---
        for alias in dup_data.get("aliases", []):
            self._aliases[alias] = canonical
            self._case_index[alias.lower()] = canonical
        # The duplicate name itself acts as an alias now
        self._aliases[duplicate] = canonical

        # --- Remove the duplicate node (its edges were already redirected) ---
        self.graph.remove_node(duplicate)

        logger.debug(
            "merge_entities: merged %r into %r", duplicate, canonical
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_entity(self, name: str) -> Optional[Entity]:
        """Return the entity record for *name*, case-insensitive."""
        lower = name.lower()
        # Try case index first, then alias index
        canonical = self._case_index.get(lower)
        if canonical is None:
            canonical = self._aliases.get(name)
        if canonical is None or not self.graph.has_node(canonical):
            return None

        data = self.graph.nodes[canonical]
        raw_mentions = [
            EntityDescription(
                text=m["text"], source=m["source"], chunk_id=m.get("chunk_id", "")
            )
            for m in data.get("raw_mentions", [])
        ]
        return Entity(
            name=canonical,
            type=data.get("type", "concept"),
            sources=list(data.get("sources", [])),
            mention_count=data.get("mention_count", 1),
            aliases=list(data.get("aliases", [])),
            raw_mentions=raw_mentions,
            current_summary=data.get("current_summary", ""),
            layer=data.get("layer"),
        )

    def query_neighbors(self, entity: str, depth: int = 1) -> List[Entity]:
        """Return entities reachable within *depth* hops (forward + backward)."""
        canonical = self._resolve(entity)
        if not self.graph.has_node(canonical):
            return []

        neighbor_names: set[str] = set()

        # Forward neighbors within depth hops
        for neighbor in nx.single_source_shortest_path_length(
            self.graph, canonical, cutoff=depth
        ):
            neighbor_names.add(neighbor)

        # Reverse neighbors (predecessors) — one hop only to match legacy
        for predecessor in self.graph.predecessors(canonical):
            neighbor_names.add(predecessor)

        # Exclude the seed entity itself
        neighbor_names.discard(canonical)

        entities: List[Entity] = []
        for n in neighbor_names:
            ent = self.get_entity(n)
            if ent is not None:
                entities.append(ent)
        return entities

    def query_neighbors_typed(
        self,
        entity: str,
        edge_types: List[str],
        depth: int = 1,
    ) -> List[Entity]:
        """Return neighbors reachable via edges whose type is in edge_types.

        Performs BFS up to *depth* hops, traversing both outgoing and incoming
        edges.  Only edges whose ``relation`` predicate appears in *edge_types*
        are followed.

        REQ-KG-760: edge-type filtering applied natively on the NetworkX graph.

        Args:
            entity: Name of the seed entity.
            edge_types: Non-empty whitelist of edge type labels.
            depth: Maximum hop depth (>= 1).

        Returns:
            Deduplicated Entity list within depth hops via matching edges.

        Raises:
            ValueError: If edge_types is empty or depth < 1.
        """
        if not edge_types:
            raise ValueError("edge_types must be a non-empty list")
        if depth < 1:
            raise ValueError("depth must be >= 1")

        edge_types_set: set[str] = set(edge_types)
        canonical = self._resolve(entity)
        if not self.graph.has_node(canonical):
            return []

        visited: set[str] = {canonical}
        # BFS queue: (node_name, current_depth)
        queue: list[tuple[str, int]] = [(canonical, 0)]
        neighbor_names: set[str] = set()

        while queue:
            current, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue

            # Outgoing edges
            for triple in self.get_outgoing_edges(current):
                if triple.predicate in edge_types_set:
                    neighbor = triple.object
                    if neighbor not in visited:
                        visited.add(neighbor)
                        neighbor_names.add(neighbor)
                        queue.append((neighbor, current_depth + 1))

            # Incoming edges
            for triple in self.get_incoming_edges(current):
                if triple.predicate in edge_types_set:
                    neighbor = triple.subject
                    if neighbor not in visited:
                        visited.add(neighbor)
                        neighbor_names.add(neighbor)
                        queue.append((neighbor, current_depth + 1))

        entities: List[Entity] = []
        for n in neighbor_names:
            ent = self.get_entity(n)
            if ent is not None:
                entities.append(ent)
        return entities

    def get_predecessors(self, entity: str) -> List[Entity]:
        """Return entities with a directed edge into *entity*."""
        canonical = self._resolve(entity)
        if not self.graph.has_node(canonical):
            return []

        entities: List[Entity] = []
        for pred in self.graph.predecessors(canonical):
            ent = self.get_entity(pred)
            if ent is not None:
                entities.append(ent)
        return entities

    # ------------------------------------------------------------------
    # Concrete overrides for edge/entity listing
    # ------------------------------------------------------------------

    def get_outgoing_edges(self, node_id: str) -> List[Triple]:
        """Return outgoing ``Triple`` edges for *node_id*.

        One Triple per (subject, predicate, object) edge-key. Parallel
        edges with different predicates produce separate Triples.
        """
        canonical = self._resolve(node_id)
        if not self.graph.has_node(canonical):
            return []
        triples: List[Triple] = []
        for _, target, key, data in self.graph.out_edges(
            canonical, keys=True, data=True
        ):
            triples.append(self._triple_from_edge(canonical, target, key, data))
        return triples

    def get_incoming_edges(self, node_id: str) -> List[Triple]:
        """Return incoming ``Triple`` edges for *node_id*.

        One Triple per (subject, predicate, object) edge-key.
        """
        canonical = self._resolve(node_id)
        if not self.graph.has_node(canonical):
            return []
        triples: List[Triple] = []
        for source_node, _, key, data in self.graph.in_edges(
            canonical, keys=True, data=True
        ):
            triples.append(self._triple_from_edge(source_node, canonical, key, data))
        return triples

    @staticmethod
    def _triple_from_edge(subject: str, obj: str, key: str, data: dict) -> Triple:
        """Construct a Triple from a MultiDiGraph edge record.

        The Triple's scalar ``evidence_span``/``chunk_id`` are populated
        from the latest observation (back-compat with single-evidence
        consumers); callers that need every observation should read
        ``backend.graph[subj][obj][predicate]["evidences"]`` directly.
        """
        sources = data.get("sources") or []
        return Triple(
            subject=subject,
            predicate=data.get("relation", key),
            object=obj,
            source=sources[0] if sources else "",
            weight=data.get("weight", 1.0),
            confidence=data.get("confidence", 1.0),
            evidence_span=data.get("evidence_span", "") or "",
            chunk_id=data.get("chunk_id", "") or "",
            extracted_at=data.get("extracted_at"),
            lhs_slice=data.get("lhs_slice"),
            rhs_slice=data.get("rhs_slice"),
            layer=data.get("layer"),
        )

    def get_all_entities(self) -> List[Entity]:
        """Return all nodes as Entity objects."""
        entities: List[Entity] = []
        for node in self.graph.nodes:
            ent = self.get_entity(node)
            if ent is not None:
                entities.append(ent)
        return entities

    def get_all_node_names_and_aliases(self) -> Dict[str, str]:
        """Return dict mapping every lowercase name/alias to canonical name."""
        # Direct read from internal index — no iteration needed
        return dict(self._case_index)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Serialize with ``orjson`` + ``nx.node_link_data``.

        Output format is backward-compatible with
        ``KnowledgeGraphBuilder.load()``.
        """
        try:
            data = nx.node_link_data(self.graph, edges="edges")
            path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        except OSError as exc:
            logger.error("save: I/O error writing graph to %s: %s", path, exc)
            raise
        except ValueError as exc:
            logger.error("save: serialization error for graph at %s: %s", path, exc)
            raise
        except Exception as exc:
            logger.error("save: unexpected error saving graph to %s: %s", path, exc)
            raise

    def load(self, path: Path) -> None:
        """Deserialize from JSON and rebuild alias/case indices."""
        try:
            raw = orjson.loads(path.read_bytes())
            self.graph = nx.node_link_graph(
                raw, directed=True, multigraph=True, edges="edges"
            )
        except OSError as exc:
            logger.error("load: I/O error reading graph from %s: %s", path, exc)
            raise
        except (orjson.JSONDecodeError, ValueError) as exc:
            logger.error("load: JSON decode error for graph at %s: %s", path, exc)
            raise
        except Exception as exc:
            logger.error("load: unexpected error loading graph from %s: %s", path, exc)
            raise

        # Rebuild indices from loaded node data
        self._aliases.clear()
        self._case_index.clear()
        for node, node_data in self.graph.nodes(data=True):
            self._case_index[node.lower()] = node
            for alias in node_data.get("aliases", []):
                self._aliases[alias] = node
                self._case_index[alias.lower()] = node

    # ------------------------------------------------------------------
    # Layer-scoped queries (source-of-origin slicing)
    # ------------------------------------------------------------------

    def subgraph_by_layer(self, layer: str) -> nx.MultiDiGraph:
        """Return a copy of the graph containing only edges for ``layer``.

        Nodes are kept iff (a) they have at least one matching edge, OR
        (b) their own ``layer`` attribute matches. Useful for inspecting
        a single source-of-origin's slice of the unified graph.
        """
        sub: nx.MultiDiGraph = nx.MultiDiGraph()
        kept_nodes: set[str] = set()

        # Nodes whose own layer attr matches.
        for node, data in self.graph.nodes(data=True):
            if data.get("layer") == layer:
                sub.add_node(node, **data)
                kept_nodes.add(node)

        # Edges whose layer matches — pull endpoints in too.
        for u, v, k, data in self.graph.edges(keys=True, data=True):
            if data.get("layer") != layer:
                continue
            if u not in kept_nodes:
                sub.add_node(u, **self.graph.nodes[u])
                kept_nodes.add(u)
            if v not in kept_nodes:
                sub.add_node(v, **self.graph.nodes[v])
                kept_nodes.add(v)
            sub.add_edge(u, v, key=k, **data)

        return sub

    def entities_by_layer(self, layer: str) -> List[Entity]:
        """Return entities whose ``layer`` attribute matches ``layer``."""
        out: List[Entity] = []
        for node, data in self.graph.nodes(data=True):
            if data.get("layer") == layer:
                ent = self.get_entity(node)
                if ent is not None:
                    out.append(ent)
        return out

    def triples_by_layer(self, layer: str) -> List[Triple]:
        """Return triples whose edge ``layer`` matches ``layer``."""
        out: List[Triple] = []
        for u, v, k, data in self.graph.edges(keys=True, data=True):
            if data.get("layer") == layer:
                out.append(self._triple_from_edge(u, v, k, data))
        return out

    def diff_layers(
        self,
        layer_a: str,
        layer_b: str,
        *,
        node_type: Optional[str] = None,
    ) -> LayerDiff:
        """Compare two layers' entity sets.

        Identity is by canonical entity name. Returns a :class:`LayerDiff`
        with ``only_in_a``, ``only_in_b``, ``in_both``, and a list of
        ``conflicting_attrs`` tuples ``(name, attr, value_in_a, value_in_b)``
        for ``in_both`` entities whose ``type`` (or other layer-tagged
        attrs visible on the node) disagree across the two layers.

        Note: because the backend stores each node only once with a sticky
        introducing-layer tag, "asserted by layer X" is interpreted as
        either (a) the node's own ``layer`` attr equals X, OR (b) the node
        participates in at least one edge whose ``layer`` equals X. This
        captures both first-introduction and subsequent reference cases.

        Args:
            layer_a: First layer name.
            layer_b: Second layer name.
            node_type: If provided, restrict comparison to entities with
                this ``type``.

        Returns:
            :class:`LayerDiff` describing set differences and per-attribute
            conflicts.
        """

        def _names_for(layer: str) -> Dict[str, dict]:
            """Map canonical name -> per-layer view dict for that layer."""
            views: Dict[str, dict] = {}
            # Nodes whose own layer matches.
            for node, data in self.graph.nodes(data=True):
                if data.get("layer") == layer:
                    if node_type is not None and data.get("type") != node_type:
                        continue
                    views[node] = {"type": data.get("type"), "name": node}
            # Nodes touched by an edge of this layer (subsequent references).
            for u, v, _k, edata in self.graph.edges(keys=True, data=True):
                if edata.get("layer") != layer:
                    continue
                for endpoint in (u, v):
                    if endpoint in views:
                        continue
                    nd = self.graph.nodes.get(endpoint, {})
                    if node_type is not None and nd.get("type") != node_type:
                        continue
                    # For "referenced by edge" rows, take the endpoint
                    # node's stored type — it's the only ground truth we
                    # have for the conflict-detection step.
                    views[endpoint] = {"type": nd.get("type"), "name": endpoint}
            return views

        view_a = _names_for(layer_a)
        view_b = _names_for(layer_b)

        names_a = set(view_a)
        names_b = set(view_b)

        only_in_a = sorted(names_a - names_b)
        only_in_b = sorted(names_b - names_a)
        in_both = sorted(names_a & names_b)

        conflicts: List = []
        # The only attr captured per layer-view today is ``type``. Adding
        # more attrs here is a forward-compatible extension.
        for name in in_both:
            a_type = view_a[name].get("type")
            b_type = view_b[name].get("type")
            if a_type != b_type:
                conflicts.append((name, "type", a_type, b_type))

        return LayerDiff(
            layer_a=layer_a,
            layer_b=layer_b,
            only_in_a=only_in_a,
            only_in_b=only_in_b,
            in_both=in_both,
            conflicting_attrs=conflicts,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def compute_rtl_reachability(self, top_module: str) -> set[str]:
        """Return the set of RTL_Module names reachable from ``top_module``.

        BFS traverses outgoing ``instantiates`` edges (parent -> child) and
        inbound ``bound_into`` edges (binder -> bind-target, so the binder
        is reached when its target is reached). The result is the set of
        nodes that are wired into the elaborated design tree rooted at
        ``top_module``; everything else among the parser-emitted
        RTL_Modules is "in the filelist but not in this build".

        Returns an empty set when ``top_module`` is not in the graph (a
        non-fatal condition the caller may wish to log).
        """
        if not self.graph.has_node(top_module):
            return set()
        seen: set[str] = {top_module}
        from collections import deque
        queue: deque[str] = deque([top_module])
        while queue:
            cur = queue.popleft()
            # Forward instantiates: parent reaches its instances.
            for _u, target, key, data in self.graph.out_edges(
                cur, keys=True, data=True
            ):
                if data.get("relation", key) == "instantiates" and target not in seen:
                    seen.add(target)
                    queue.append(target)
            # Inbound bound_into: bind sources are reached via the bind target.
            for source, _v, key, data in self.graph.in_edges(
                cur, keys=True, data=True
            ):
                if data.get("relation", key) == "bound_into" and source not in seen:
                    seen.add(source)
                    queue.append(source)
        return seen

    def stats(self) -> Dict[str, object]:
        """Return node count, edge count, and top-10 most-mentioned entities."""
        top = sorted(
            self.graph.nodes(data=True),
            key=lambda x: x[1].get("mention_count", 0),
            reverse=True,
        )[:10]
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "top_entities": [name for name, _ in top],
        }
