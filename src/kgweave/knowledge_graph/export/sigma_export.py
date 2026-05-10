# @summary
# Interactive HTML graph visualization using Sigma.js + graphology from CDN.
# Exports: export_html
# Deps: json, pathlib, src.knowledge_graph.backend
# @end-summary
"""Interactive HTML graph visualization using Sigma.js.

Generates a single self-contained HTML file with embedded graph data,
Sigma.js v3 and graphology loaded from CDN.  No pip dependency required.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from kgweave.knowledge_graph.community import CommunityDetector

from kgweave.knowledge_graph.backend import GraphStorageBackend

__all__ = ["export_html"]

logger = logging.getLogger("rag.knowledge_graph.export.sigma")

# Deterministic color palette for types/communities
_PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9a6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
]

# Edge predicates grouped by semantic class. Each class has a coherent hue
# family so the visual encoding carries meaning:
#   * Composition (warm red-orange, hue 0–60°): parent owns child. Following
#     the arrow goes "into" the parent's structure.
#   * Dependency (blue, hue 180–220°): subject needs object. Arrow points to
#     what the subject relies on.
#   * Dataflow (green, hue 90–160°): signal/data flows from source to sink.
#   * Reference (purple/gray, hue 240–320° or near-zero saturation): subject
#     mentions or points at object without owning or depending on it.
#
# Sigma v3 ships only "line" and "arrow" edge programs by default, so we
# encode visual variation via colour + size and leave the Sigma edge type as
# "arrow" everywhere.
_EDGE_CLASSES: Dict[str, Dict[str, str]] = {
    "Composition": {
        # part_of is the inverse direction of the others but still expresses
        # composition semantics; classified here for legend coherence.
        "contains":        "#e67e22",
        "has_register":    "#d35400",
        "has_field":       "#e88a36",
        "has_fsm":         "#cb4335",
        "has_state":       "#e74c3c",
        "has_assertion":   "#a93226",
        # SystemVerilog `bind` injects the bound module/interface into the
        # target's hierarchy — composition-shaped (warm wedge).
        "bound_into":      "#9c2a1e",
        "instantiates":    "#b34700",
        "part_of":         "#c0392b",
        # Covergroup belongs inside an RTL module.
        "collected_in":    "#dc7633",
        # Covergroup_SV owns its sample-function formal arguments.
        "has_sample_arg":  "#e06c1a",
        # DVTest → SV_File (test code realization)
        "realized_by":     "#d98880",
        # IP-XACT composition: component owns ports / registers / fields /
        # bus interfaces (parallel to RTL contains-style ownership).
        "has_ipxact_port":     "#bf5a15",
        "has_ipxact_register": "#a04000",
        "has_ipxact_field":    "#ba4a00",
        "has_bus_interface":   "#d35400",
        # IP-XACT Phase-2 composition: address blocks, enums, params, filesets.
        "has_address_block":   "#cc5a17",
        "contains_register":   "#9c3d00",
        "has_ipxact_enum":     "#b04508",
        "has_ipxact_parameter":"#c75d10",
        "has_ipxact_fileset":  "#a64500",
        # IP-XACT Phase-2b composition: bus-interface portMap + memoryMap chain.
        "has_logical_port":    "#e08e2a",
        "has_memory_map":      "#b85510",
        "contains_address_block": "#8a3500",
        # Spec-claim composition: a Section owns the claims it asserts; a
        # parent claim composes its children.
        "claims_about":        "#e07b1f",
        "decomposes_into":     "#c2660c",
        # C/C++ ref-model file inclusion (CFile includes CFile).
        "includes":            "#e59030",
        # UVMSampleCallsite owns its positional UVMSampleArgExpr nodes —
        # composition wedge (warm hue distinct from existing entries).
        "passes_arg":          "#f0a040",
    },
    "Dependency": {
        "clocked_by":        "#2980b9",
        "reset_by":          "#1f618d",
        "depends_on":        "#2874a6",
        "instance_of":       "#2c7fb8",
        "specified_by":      "#3498db",
        "binds_parameter":   "#1a5490",
        # SDC constraints — anchor design entities to timing intent.
        "constrains_clock":  "#5499c7",
        "constrains_port":   "#7fb3d5",
        "relative_to_clock": "#21618c",
        "from_endpoint":     "#1b4f72",
        "to_endpoint":       "#154360",
        "groups_clock":      "#5dade2",
        # IP-XACT specifies: an IPXACT_X declares the existence/shape of a
        # canonical X (Port / ClockDomain / CSR_Register / etc.). The
        # IPXACT side is the "source of truth" the canonical depends on
        # — Dependency class fits cleanly.
        "specifies":         "#3a86b8",
    },
    "Dataflow": {
        "drives":          "#27ae60",
        # connects_to is legacy/undirected; closest fit is dataflow shape.
        "connects_to":     "#229954",
        # transitions_to (FSM next-state) is dataflow-shaped: state flows
        # from one to the next.
        "transitions_to":  "#1e8449",
        # reads is intra-module signal-level dataflow (LHS reads RHS).
        # Distinct teal-green from drives (cross-module) so the legend
        # disambiguates the two.
        "reads":           "#0f9f6c",
    },
    "Reference": {
        "references":         "#7f8c8d",
        "mentions":           "#8e44ad",
        "references_signal":  "#884ea0",
        # Testplan edges: testpoint mentions a test / stage / assertion.
        "tests":              "#9b59b6",
        "has_stage":          "#76448a",
        "covers":             "#a569bd",
        # SystemVerilog covergroup-side composition + sampling edges.
        # Coverpoints reference signals (no ownership / dataflow), so the
        # whole family lives in the Reference class. Hues stay inside the
        # 240–320 wedge to keep the legend palette test happy.
        "has_coverpoint":     "#6c3483",
        "has_bin":            "#5b2c6f",
        "has_cross":          "#7d3c98",
        "observes":           "#9b6bbf",
        "crosses":            "#bb8fce",
        "defined_in":         "#633974",
        # Spec-claim → evidence pointers. Claim nodes reference downstream
        # canonical entities (target / SVA / testpoint / coverpoint) without
        # owning them, so the family lives in Reference.
        "target_entity":      "#7d3c98",
        "enforced_by":        "#884ea0",
        "covered_by":         "#a569bd",
        "measured_by":        "#bb8fce",
        # C/C++ ref-model DPI-C and SW-test reference edges.
        "imports_dpi":        "#9b7dbf",
        "implements_dpi":     "#b89fd0",
        "tests_module":       "#c0a0d8",
        "accesses_csr":       "#d0b8e0",
        # IP-XACT cross-source: declarative source pointing at canonical
        # RTL realization. Purple wedge (274-283 hue family).
        "parameterizes":      "#8e5ec4",
        "implemented_by":     "#a48bd0",
        # IP-XACT Phase-2b reference: bus-interface to RTL/protocol hops.
        "conforms_to":               "#7548b3",
        "aggregates_port":           "#9e76d9",
        "physical_for":              "#b89be5",
        "exposes_memory_map":        "#6f3fb0",
        "connects_to_address_space": "#5a2f95",
        # UVM sample-callsite audit wedge — five distinct purple shades so
        # the legend visually separates the sample-side discovery edges.
        "samples_covergroup":  "#5b3a96",
        "wraps_covergroup":    "#7a4fb5",
        "via_wrapper":         "#9670c8",
        "defined_in_uvm_file": "#b292d8",
        "binds_to_arg":        "#cdb3e8",
    },
}

# Flat back-compat alias: predicate -> {"color": "#..."}.  Existing call sites
# (and tests) that look up styles by predicate name still work unchanged.
_EDGE_STYLES: Dict[str, Dict[str, str]] = {
    pred: {"color": color}
    for cls in _EDGE_CLASSES.values()
    for pred, color in cls.items()
}

# Reverse index: predicate -> class name.  Used when filtering the legend
# down to predicates actually used in a given graph.
_EDGE_CLASS_OF: Dict[str, str] = {
    pred: cls_name
    for cls_name, cls in _EDGE_CLASSES.items()
    for pred in cls
}

_DEFAULT_EDGE_STYLE = {"color": "#cccccc"}

# Muted style for RTL_Module nodes whose ``reachable=false`` alias is set.
# Applied via opacity-encoded hex (8-digit RGBA, ``99`` ~= 60% alpha) so the
# Sigma circle program can render it without a custom shader. Gray-blue keeps
# them visually demoted vs. the reachable cluster but still clickable.
_UNREACHABLE_RTL_COLOR = "#7a8a99"
_UNREACHABLE_RTL_OPACITY = 0.6

# Display-only label decoration for Port nodes. Maps the entity's
# ``port_direction`` to a short suffix appended to the node's
# ``display_type`` attribute. The underlying ``entityType`` field stays
# ``"Port"`` so downstream consumers (community detection, retrieval,
# tests that inspect entity type) are unaffected — this is purely a
# rendering hint for the Sigma legend / tooltip.
_PORT_DIRECTION_LABEL: Dict[str, str] = {
    "input":  "Port [In]",
    "output": "Port [Out]",
    "inout":  "Port [InOut]",
}

# Default ``include_layers`` whitelist when the caller passes ``None``.
# Hides v2 ``ast`` layer content (Operator/Literal/Branch/etc) which is only
# relevant to the RTL-debug persona. Unlayered nodes (no ``layer`` attr set)
# are unconditionally visible regardless of this set, for v1 backward compat.
#
# Implementation note: we use *exclude* semantics for the default rather than
# a positive whitelist because the layer namespace is open — every extractor
# (sv_parser, hjson_csr, testplan, dv_test_realization, dpi_boundary,
# cpp_ref_model, uvm_sample, llm_doc, etc.) introduces its own layer tag, and
# a positive whitelist silently drops new layers as they're added. The schema
# contract is "everything except ast"; encode that directly.
_DEFAULT_EXCLUDE_LAYERS: Set[str] = {"ast"}

# Sentinel string accepted as ``include_layers="all"`` to render every layer
# regardless of tag (RTL-debug persona, full-graph diagnostic exports).
_LAYER_SENTINEL_ALL = "all"

# Symbolic rendering for common Operator ``kind`` values. Keys match the
# ``attributes["kind"]`` string emitted by the slang AST walker; missing
# entries fall back to the raw kind string in ``_display_type``.
_OPERATOR_SYMBOLS: Dict[str, str] = {
    "LogicalAnd":          "&&",
    "LogicalOr":           "||",
    "LogicalNot":          "!",
    "BinaryAnd":           "&",
    "BinaryOr":            "|",
    "BinaryXor":           "^",
    "BinaryXnor":          "~^",
    "BitwiseNot":          "~",
    "Add":                 "+",
    "Subtract":            "-",
    "Multiply":            "*",
    "Divide":              "/",
    "Modulo":              "%",
    "Equality":            "==",
    "Inequality":          "!=",
    "CaseEquality":        "===",
    "CaseInequality":      "!==",
    "LessThan":            "<",
    "LessThanEqual":       "<=",
    "GreaterThan":         ">",
    "GreaterThanEqual":    ">=",
    "LogicalShiftLeft":    "<<",
    "LogicalShiftRight":   ">>",
    "ArithmeticShiftLeft": "<<<",
    "ArithmeticShiftRight":">>>",
    "Conditional":         "?:",
}


def _resolve_include_layers(
    include_layers: Union[Set[str], List[str], str, None],
) -> Tuple[Optional[Set[str]], Set[str]]:
    """Normalise ``include_layers`` into ``(allow_set, deny_set)``.

    - ``allow_set=None`` means "no positive whitelist applied".
    - ``deny_set`` is always a concrete (possibly empty) set.

    Resolution rules:

    - ``include_layers is None`` (default) → allow=None, deny=``{"ast"}``.
      The structural-consumer view: render every layer except ``ast``.
    - ``include_layers == "all"`` → allow=None, deny=``set()``.
      Render everything (RTL-debug full-graph diagnostic).
    - ``include_layers`` is a set/list → allow=set(...), deny=set(). The
      caller is being explicit about what to render; honor the whitelist
      verbatim and apply no implicit deny.
    - ``include_layers`` is any other string → treated as a single-layer
      whitelist (defensive footgun).
    """
    if include_layers is None:
        return None, set(_DEFAULT_EXCLUDE_LAYERS)
    if isinstance(include_layers, str):
        if include_layers == _LAYER_SENTINEL_ALL:
            return None, set()
        return {include_layers}, set()
    return set(include_layers), set()


def _layer_allows(
    item_layer: Optional[str], filt: Tuple[Optional[Set[str]], Set[str]]
) -> bool:
    """Return True iff a node/edge with ``item_layer`` should render.

    - Unlayered items (``item_layer`` falsy) are always allowed for v1
      backward compat.
    - Otherwise, must satisfy both: not in ``deny`` AND (``allow`` is None
      OR in ``allow``).
    """
    if not item_layer:
        return True
    allow, deny = filt
    if item_layer in deny:
        return False
    if allow is None:
        return True
    return item_layer in allow


def _display_type(
    entity_type: str,
    port_direction: Optional[str],
    attributes: Optional[Dict[str, Any]] = None,
) -> str:
    """Return the Sigma display label for a node's type cell.

    Non-Port entities get their type verbatim. Port entities get a
    direction suffix (``[In]`` / ``[Out]`` / ``[InOut]``); ports with no
    classifiable direction render as plain ``Port``.

    V2 AST node types use richer labels derived from ``attributes``:

    - ``Operator`` → ``"Op: <symbol>"`` (e.g. ``"Op: &&"``) when the
      ``kind`` is in the symbol map; otherwise the raw kind string.
    - ``Literal`` → the literal's ``text`` (e.g. ``"32'h0"``).
    - ``Branch`` → ``"Branch (depth N)"`` where N is the length of the
      ``branch_path`` list.

    Other v2 types (``IfStatement`` / ``CaseStatement`` / ``Loop`` /
    ``Assignment`` / ``Condition`` / ``Index``) keep their type string as-is.
    """
    if entity_type == "Port":
        return _PORT_DIRECTION_LABEL.get(port_direction or "", "Port")
    attrs = attributes or {}
    if entity_type == "Operator":
        kind = attrs.get("kind") or "Operator"
        symbol = _OPERATOR_SYMBOLS.get(kind)
        return f"Op: {symbol}" if symbol else kind
    if entity_type == "Literal":
        text = attrs.get("text")
        return text if text else "Literal"
    if entity_type == "Branch":
        path = attrs.get("branch_path") or []
        try:
            depth = len(path)
        except TypeError:
            depth = 0
        return f"Branch (depth {depth})"
    return entity_type


def _entity_attributes(entity, backend) -> Dict[str, Any]:
    """Return the free-form ``attributes`` dict for an entity.

    ``Entity.attributes`` is populated by some extractor paths but the
    backend's ``get_entity`` projection doesn't surface it. Fall back to
    reading directly from ``backend.graph`` node data when available.
    """
    attrs = getattr(entity, "attributes", None) or {}
    if attrs:
        return attrs
    if hasattr(backend, "graph"):
        try:
            return backend.graph.nodes[entity.name].get("attributes") or {}
        except (KeyError, AttributeError):
            return {}
    return {}


def _is_unreachable_rtl(entity) -> bool:
    """Return True iff entity is an RTL_Module tagged ``reachable=false``.

    The tag lives on ``entity.aliases`` as a structured ``key=value`` string
    (consistent with how other post-processed attrs are stored).
    """
    if entity.type != "RTL_Module":
        return False
    for alias in entity.aliases or ():
        if isinstance(alias, str) and alias == "reachable=false":
            return True
    return False


def _type_color(type_name: str) -> str:
    """Deterministic color from type name."""
    idx = int(hashlib.md5(type_name.encode()).hexdigest(), 16) % len(_PALETTE)
    return _PALETTE[idx]


def _build_graph_json(
    backend: GraphStorageBackend,
    community_detector: Optional["CommunityDetector"] = None,
    include_types: Optional[List[str]] = None,
    include_layers: Union[Set[str], List[str], str, None] = None,
) -> Dict[str, Any]:
    """Build the graph data structure for Sigma.js rendering.

    See ``export_html`` for the ``include_layers`` semantics.
    """
    layer_allow = _resolve_include_layers(include_layers)

    entities = backend.get_all_entities()
    if include_types is not None:
        allow = set(include_types)
        entities = [e for e in entities if e.type in allow]
    # Apply layer filter independently of include_types — a node must pass
    # both gates to render. ``_layer_allows`` keeps unlayered (v1 legacy)
    # entities visible regardless.
    entities = [e for e in entities if _layer_allows(getattr(e, "layer", None), layer_allow)]
    if include_types is not None or layer_allow is not None:
        kept = {e.name for e in entities}
    else:
        kept = None
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    type_colors: Dict[str, str] = {}
    community_colors: Dict[str, str] = {}
    community_sizes: Dict[int, int] = {}
    edge_id = 0
    coloring_mode = "type"

    emitted_node_keys: set[str] = set()

    def _emit_entity_node(entity) -> None:
        nonlocal coloring_mode
        community_id = None
        if community_detector is not None:
            # get_community_for_entity safely returns None when detection
            # has not been run, so we don't need to gate on summaries.
            community_id = community_detector.get_community_for_entity(entity.name)

        color = _type_color(entity.type)
        type_colors[entity.type] = color

        if community_id is not None and community_id >= 0:
            color = _PALETTE[community_id % len(_PALETTE)]
            coloring_mode = "community"
            community_colors[f"community {community_id}"] = color
            community_sizes[community_id] = community_sizes.get(community_id, 0) + 1

        size = max(3, min(20, entity.mention_count or 1))

        # Demote unreachable RTL_Modules so the layout doesn't cluster them
        # into their own bright community. They stay clickable; only the
        # visual weight changes.
        unreachable = _is_unreachable_rtl(entity)
        if unreachable:
            color = _UNREACHABLE_RTL_COLOR

        # ``port_direction`` lives on the backend node-data dict (set by
        # the slang/parser extractors). ``Entity`` carries it too, but
        # ``get_entity()`` doesn't currently surface it — read from the
        # graph for backends that expose it directly, fall back to the
        # entity field otherwise.
        port_direction: Optional[str] = getattr(entity, "port_direction", None)
        if port_direction is None and hasattr(backend, "graph"):
            try:
                port_direction = backend.graph.nodes[entity.name].get(
                    "port_direction"
                )
            except (KeyError, AttributeError):
                port_direction = None

        nodes.append({
            "key": entity.name,
            "attributes": {
                "label": entity.name,
                # Sigma v3 reserves "type" for its renderer program selector
                # (e.g. "circle", "image"). Carry the entity type under a
                # different key so the default circle program is used.
                "entityType": entity.type,
                # Display-only label — Port nodes get a direction suffix
                # so the Sigma legend distinguishes ``Port [In]`` etc.
                # without mutating ``entityType``.
                "display_type": _display_type(
                    entity.type,
                    port_direction,
                    _entity_attributes(entity, backend),
                ),
                "community": community_id,
                "size": size,
                "color": color,
                "sources": ", ".join(entity.sources[:3]),
                "mentions": entity.mention_count,
                "reachable": not unreachable,
                "opacity": _UNREACHABLE_RTL_OPACITY if unreachable else 1.0,
            },
        })
        emitted_node_keys.add(entity.name)

    for entity in entities:
        _emit_entity_node(entity)

    # Sweep the backend graph for any node that wasn't emitted as an
    # explicit Entity (e.g. signal nodes auto-created by ``add_edge``
    # without a corresponding ``upsert_entities`` call). These would
    # otherwise become dangling targets when we emit the full edge set
    # below. Skipped for backends that don't expose a NetworkX-style
    # ``.graph`` (e.g. Neo4j) — there, ``get_all_entities`` is canonical.
    if hasattr(backend, "graph") and hasattr(backend.graph, "nodes"):
        for node_name, node_data in backend.graph.nodes(data=True):
            if node_name in emitted_node_keys:
                continue
            entity_type = node_data.get("type") or "Signal"
            if kept is not None and entity_type not in kept and node_name not in kept:
                # Respect include_types: don't surface an auto-created
                # node whose type isn't in the whitelist.
                continue
            # Respect include_layers on auto-created nodes too. Unlayered
            # (legacy / placeholder) nodes always pass — keeps v1 graphs
            # rendering identically.
            if not _layer_allows(node_data.get("layer"), layer_allow):
                continue
            color = _type_color(entity_type)
            type_colors[entity_type] = color
            mentions = node_data.get("mention_count", 1) or 1
            size = max(3, min(20, mentions))
            sources = list(node_data.get("sources", []) or [])
            port_direction = node_data.get("port_direction")
            node_attributes = node_data.get("attributes") or {}
            nodes.append({
                "key": node_name,
                "attributes": {
                    "label": node_name,
                    "entityType": entity_type,
                    "display_type": _display_type(
                        entity_type, port_direction, node_attributes
                    ),
                    "community": None,
                    "size": size,
                    "color": color,
                    "sources": ", ".join(sources[:3]),
                    "mentions": mentions,
                    "reachable": True,
                    "opacity": 1.0,
                },
            })
            emitted_node_keys.add(node_name)

    # Full-graph edge sweep. Iterating per-entity via ``get_outgoing_edges``
    # would skip outbound edges from auto-created nodes that aren't in the
    # explicit entities list (notably the ~7k ``drives_signal`` edges
    # produced by the dataflow extractor). Walking ``backend.graph.edges``
    # captures every edge in the graph in a single pass.
    if hasattr(backend, "graph") and hasattr(backend.graph, "edges"):
        edge_iter = backend.graph.edges(keys=True, data=True)
        for subj, obj, key, data in edge_iter:
            if subj not in emitted_node_keys or obj not in emitted_node_keys:
                # Respect include_types filtering: any edge touching a
                # node we chose not to emit gets dropped (matches prior
                # ``kept`` semantics).
                continue
            # Respect include_layers on edge tags. An edge whose own
            # ``layer`` is not in the whitelist is hidden even if both
            # endpoints survive the node filter (e.g. an ast-layer
            # ``operand`` edge stitched between two slang Port nodes).
            if not _layer_allows(data.get("layer"), layer_allow):
                continue
            predicate = data.get("relation", key)
            style = _EDGE_STYLES.get(predicate, _DEFAULT_EDGE_STYLE)
            sources = data.get("sources") or []
            edges.append({
                "key": f"e{edge_id}",
                "source": subj,
                "target": obj,
                "attributes": {
                    "label": predicate,
                    "color": style["color"],
                    "size": 1.5,
                    "predicate": predicate,
                    "lhs_slice": data.get("lhs_slice"),
                    "rhs_slice": data.get("rhs_slice"),
                    "evidence_span": data.get("evidence_span", "") or "",
                    "edgeSource": sources[0] if sources else "",
                },
            })
            edge_id += 1
    else:
        # Fallback for non-NetworkX backends: walk per-entity outbound
        # edges via the public API (no guarantee of full-graph coverage,
        # but matches prior behavior).
        for entity in entities:
            for triple in backend.get_outgoing_edges(entity.name):
                if kept is not None and triple.object not in kept:
                    continue
                if not _layer_allows(getattr(triple, "layer", None), layer_allow):
                    continue
                style = _EDGE_STYLES.get(triple.predicate, _DEFAULT_EDGE_STYLE)
                edges.append({
                    "key": f"e{edge_id}",
                    "source": triple.subject,
                    "target": triple.object,
                    "attributes": {
                        "label": triple.predicate,
                        "color": style["color"],
                        "size": 1.5,
                        "predicate": triple.predicate,
                        "lhs_slice": triple.lhs_slice,
                        "rhs_slice": triple.rhs_slice,
                        "evidence_span": triple.evidence_span,
                        "edgeSource": triple.source,
                    },
                })
                edge_id += 1

    # Order communities by size descending so the legend reads top-down
    # from the largest cluster, then truncate so we don't blow past the
    # legend container on big graphs.
    sorted_community_colors = dict(
        sorted(
            community_colors.items(),
            key=lambda kv: community_sizes.get(int(kv[0].split()[1]), 0),
            reverse=True,
        )[:20]
    )

    # Group edges in the legend by semantic class, filtered to predicates
    # that actually appear in the rendered graph.
    used_predicates = {e["attributes"]["label"] for e in edges
                       if e["attributes"].get("label")}
    edge_classes_legend: Dict[str, List[Dict[str, str]]] = {}
    for cls_name, cls_map in _EDGE_CLASSES.items():
        entries = [
            {"predicate": pred, "color": color}
            for pred, color in cls_map.items()
            if pred in used_predicates
        ]
        if entries:
            edge_classes_legend[cls_name] = entries

    return {
        "nodes": nodes,
        "edges": edges,
        "legend": {
            "mode": coloring_mode,
            "type_colors": type_colors,
            "community_colors": sorted_community_colors,
            "community_sizes": {str(k): v for k, v in community_sizes.items()},
            # Back-compat: flat predicate -> colour mapping.
            "edge_styles": {k: v["color"] for k, v in _EDGE_STYLES.items()},
            # Grouped, filtered legend used by the renderer.
            "edge_classes": edge_classes_legend,
        },
    }


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>RagWeave Knowledge Graph</title>
  <script src="https://unpkg.com/graphology@0.25.4/dist/graphology.umd.min.js"></script>
  <script src="https://unpkg.com/sigma@3.0.3/dist/sigma.min.js"></script>
  <script src="https://unpkg.com/graphology-library@0.7.1/dist/graphology-library.min.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; overflow: hidden; }
    #graph-container { width: 100vw; height: 100vh; }
    #search-container {
      position: absolute; top: 10px; left: 10px; z-index: 10;
      background: rgba(255,255,255,0.95); padding: 8px; border-radius: 6px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }
    #search-input {
      width: 250px; padding: 6px 10px; border: 1px solid #ddd;
      border-radius: 4px; font-size: 14px;
    }
    #legend {
      position: absolute; bottom: 10px; left: 10px; z-index: 10;
      background: rgba(255,255,255,0.95); padding: 10px; border-radius: 6px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15); max-height: 200px; overflow-y: auto;
      font-size: 12px;
    }
    .legend-item { display: flex; align-items: center; margin: 3px 0; }
    .legend-dot {
      width: 10px; height: 10px; border-radius: 50%;
      margin-right: 6px; flex-shrink: 0;
    }
    #tooltip {
      position: absolute; z-index: 20; background: rgba(0,0,0,0.85);
      color: white; padding: 8px 12px; border-radius: 4px; font-size: 12px;
      pointer-events: none; display: none; max-width: 300px;
    }
    #info {
      position: absolute; top: 10px; right: 10px; z-index: 10;
      background: rgba(255,255,255,0.95); padding: 8px 12px; border-radius: 6px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15); font-size: 13px;
    }
  </style>
</head>
<body>
  <div id="search-container">
    <input id="search-input" type="text" placeholder="Search entities..." />
  </div>
  <div id="graph-container"></div>
  <div id="legend"></div>
  <div id="tooltip"></div>
  <div id="info"></div>
  <script>
    const graphData = __GRAPH_DATA__;

    // Build graph
    const graph = new graphology.Graph({multi: false, type: "directed"});
    graphData.nodes.forEach(n => {
      // ForceAtlas2 needs initial positions; without them every coord becomes NaN.
      const attrs = Object.assign({
        x: Math.random(),
        y: Math.random(),
      }, n.attributes);
      graph.addNode(n.key, attrs);
    });
    graphData.edges.forEach(e => {
      if (graph.hasNode(e.source) && graph.hasNode(e.target)) {
        try { graph.addEdge(e.source, e.target, e.attributes); } catch(err) {}
      }
    });

    // Layout — graphology-library@0.7 exposes layoutForceAtlas2 under graphologyLibrary
    const FA2 = graphologyLibrary.layoutForceAtlas2;
    const settings = FA2.inferSettings(graph);
    FA2.assign(graph, {settings, iterations: 200});

    // Render
    const container = document.getElementById("graph-container");
    const renderer = new Sigma(graph, container, {
      renderEdgeLabels: false,
      labelRenderedSizeThreshold: 8,
      defaultEdgeType: "arrow",
      defaultNodeType: "circle",
      enableEdgeEvents: true,
    });

    // Info
    document.getElementById("info").textContent =
      `${graph.order} nodes, ${graph.size} edges`;

    // Legend — reflect whatever coloring mode the export actually used
    const legendEl = document.getElementById("legend");
    const legend = graphData.legend;
    const isCommunity = legend.mode === "community";
    const titleText = isCommunity
      ? `Communities (top ${Object.keys(legend.community_colors).length} by size)`
      : "Entity types";
    const colorMap = isCommunity ? legend.community_colors : legend.type_colors;
    const sizes = legend.community_sizes || {};

    const title = document.createElement("div");
    title.style.fontWeight = "600";
    title.style.marginBottom = "4px";
    title.textContent = titleText;
    legendEl.appendChild(title);

    Object.entries(colorMap).forEach(([label, color]) => {
      const item = document.createElement("div");
      item.className = "legend-item";
      let display = label;
      if (isCommunity) {
        const cid = label.split(" ")[1];
        const n = sizes[cid];
        display = `${label}${n ? ` (${n})` : ""}`;
      }
      item.innerHTML = `<span class="legend-dot" style="background:${color}"></span>${display}`;
      legendEl.appendChild(item);
    });

    // Edge-predicate legend grouped by semantic class. Each class is its
    // own bold subsection (Composition / Dependency / Dataflow / Reference);
    // we skip a class entirely if no predicates of that class appear in
    // the rendered graph, so the key stays compact.
    const usedPredicates = new Set(
      graphData.edges.map(e => e.attributes && e.attributes.label).filter(Boolean)
    );
    const edgeClasses = legend.edge_classes || {};
    const classOrder = ["Composition", "Dependency", "Dataflow", "Reference"];
    classOrder.forEach(cls => {
      const entries = (edgeClasses[cls] || [])
        .filter(e => usedPredicates.has(e.predicate));
      if (entries.length === 0) return;
      const header = document.createElement("div");
      header.style.fontWeight = "700";
      header.style.fontSize = "11px";
      header.style.marginTop = "8px";
      header.style.marginBottom = "3px";
      header.textContent = cls;
      legendEl.appendChild(header);
      entries.forEach(({predicate, color}) => {
        const item = document.createElement("div");
        item.className = "legend-item";
        item.innerHTML = `<span style="display:inline-block;width:18px;height:3px;background:${color};margin-right:6px;vertical-align:middle;flex-shrink:0;"></span>${predicate}`;
        legendEl.appendChild(item);
      });
    });

    // Search
    const searchInput = document.getElementById("search-input");
    searchInput.addEventListener("input", () => {
      const query = searchInput.value.toLowerCase();
      graph.forEachNode((node, attrs) => {
        const match = !query || attrs.label.toLowerCase().includes(query);
        graph.setNodeAttribute(node, "hidden", !match && query.length > 0);
      });
      renderer.refresh();
    });

    // Tooltip — single tooltip surfaces node OR edge data depending on
    // what the cursor is over. Edge tooltip exposes bit-slice / evidence
    // info that only lives on edge attrs (notably for `reads` dataflow).
    const tooltip = document.getElementById("tooltip");
    const escapeHtml = (s) => String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    renderer.on("enterNode", ({node}) => {
      const attrs = graph.getNodeAttributes(node);
      tooltip.innerHTML = `<b>${escapeHtml(attrs.label)}</b><br>Type: ${escapeHtml(attrs.entityType)}<br>Mentions: ${attrs.mentions}<br>Sources: ${escapeHtml(attrs.sources) || "n/a"}`;
      tooltip.style.display = "block";
    });
    renderer.on("leaveNode", () => { tooltip.style.display = "none"; });
    renderer.on("enterEdge", ({edge}) => {
      const a = graph.getEdgeAttributes(edge);
      const [s, t] = graph.extremities(edge);
      const lines = [
        `<b>${escapeHtml(s)}</b> &rarr; <b>${escapeHtml(t)}</b>`,
        `Predicate: ${escapeHtml(a.predicate || a.label)}`,
      ];
      if (a.lhs_slice || a.rhs_slice) {
        lines.push(`Slice: lhs=${escapeHtml(a.lhs_slice) || "—"} rhs=${escapeHtml(a.rhs_slice) || "—"}`);
      }
      if (a.evidence_span) {
        lines.push(`Evidence: <code>${escapeHtml(a.evidence_span)}</code>`);
      }
      if (a.edgeSource) {
        lines.push(`Source: ${escapeHtml(a.edgeSource)}`);
      }
      tooltip.innerHTML = lines.join("<br>");
      tooltip.style.display = "block";
    });
    renderer.on("leaveEdge", () => { tooltip.style.display = "none"; });
    renderer.getMouseCaptor().on("mousemove", (e) => {
      tooltip.style.left = e.x + 15 + "px";
      tooltip.style.top = e.y + 15 + "px";
    });
  </script>
</body>
</html>"""


def export_html(
    backend: GraphStorageBackend,
    output_path: str,
    community_detector: Optional["CommunityDetector"] = None,
    include_types: Optional[List[str]] = None,
    include_layers: Union[Set[str], List[str], str, None] = None,
) -> int:
    """Generate a self-contained interactive HTML graph visualization.

    Args:
        backend: Graph storage backend to export from.
        output_path: Path for the output HTML file.
        community_detector: Optional detector for community-based coloring.
        include_types: Optional whitelist of entity types to render. When
            given, both nodes and edges referencing other types are dropped.
        include_layers: Optional whitelist of source-of-origin layers to
            render. Three forms are accepted:

            * ``None`` (default) — render the structural-consumer view:
              ``{"slang", "sdc", "ipxact", "markdown_doc", "spec_claim",
              "sw_test"}``. **The v2 ``"ast"`` layer (Operator / Literal /
              Branch / Condition / IfStatement / etc.) is hidden by
              default** so audit / DV / spec consumers aren't drowned in
              expression internals. RTL-debug callers must opt in.
            * An explicit ``set[str]`` — used verbatim. Pass
              ``{"slang", "ast"}`` for the full RTL-debug view.
            * The string sentinel ``"all"`` — disables layer filtering
              entirely (every layer renders).

            Nodes and edges with no ``layer`` attribute set (legacy v1
            graphs) always render regardless of this setting.

    Returns:
        Number of nodes rendered.
    """
    graph_data = _build_graph_json(
        backend, community_detector, include_types, include_layers
    )
    html = _HTML_TEMPLATE.replace("__GRAPH_DATA__", json.dumps(graph_data))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

    node_count = len(graph_data["nodes"])
    logger.info("Exported %d nodes to %s", node_count, output_path)
    return node_count
