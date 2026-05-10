"""Predicate-collision audit and adversarial round-trip tests.

Why this file exists
--------------------
NetworkX ``DiGraph`` collapses parallel edges between the same
``(subject, object)`` pair into a single edge record keyed by node-pair.
That means if **any two extractors** (or even a single extractor) emit
two different predicates between the same pair of nodes, the second
``add_edge`` call will overwrite the first observation's predicate,
weight, evidence_span, chunk_id, and extracted_at.

The trigger that revealed the bug:
    The slang connectivity extractor used to emit BOTH ``connects_to``
    (legacy back-compat) and ``drives`` (directional) between the same
    instance-port and net pair. Whichever was upserted second silently
    shadowed the first. Every unit test passed; the bug only surfaced
    on a real OpenTitan integration query that depended on directional
    information. See ``sv_connectivity._emit_port_connections`` —
    ``connects_to`` was deleted from the emit path.

This file does three things:

1. **Predicate matrix**: documents which (source_type, target_type, predicate)
   tuples each extractor can emit. Acts as a structural reference for
   reviewers; if a new extractor or predicate is added, this matrix must
   be updated.
2. **Collision detection**: scans the matrix and asserts no two predicates
   share the same (source_type, target_type) pair across the full union of
   extractors. Known/expected collisions are documented inline.
3. **Adversarial round-trip tests**: prove via the live ``NetworkXBackend``
   that the DiGraph collapse hazards still exist; these are marked
   ``xfail`` so they document the known limitation without breaking CI.
   They will start passing only after the planned MultiDiGraph migration.

Convention
----------
Every extractor should have at least one round-trip integration test that
extracts → upserts via ``NetworkXBackend`` → queries via
``get_outgoing_edges`` / ``get_all_entities`` and asserts results match
what the extractor emitted. See sibling test files for examples.
"""
from __future__ import annotations

from typing import Dict, List, Set, Tuple

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Entity, Triple


# ---------------------------------------------------------------------------
# Predicate matrix — manually curated by reading every extractor module.
# Update this when adding a predicate or a new extractor.
# ---------------------------------------------------------------------------
#
# Schema: extractor_name -> list of (source_type, target_type, predicate)
# tuples. ``"*"`` means the extractor can emit any node type (e.g. LLM-driven
# extraction governed only by the YAML schema).
EXTRACTOR_PREDICATE_MATRIX: Dict[str, List[Tuple[str, str, str]]] = {
    # -- regex_extractor.py: lines 301, 317, 330, 345, 359 --
    # Subject and object types are produced by ``classify_type``: one of
    # ``concept`` / ``technology`` / ``acronym``. We treat them all as
    # ``concept-like`` for collision purposes — the matrix groups them
    # under the bucket ``concept`` because that's what the patterns produce
    # for free-text relations, and is_a/subset_of/used_for/uses can occur
    # between any pair of those.
    "regex": [
        ("concept", "concept", "is_a"),
        ("concept", "concept", "subset_of"),
        ("concept", "concept", "used_for"),
        ("concept", "concept", "uses"),
    ],
    # -- gliner_extractor.py: delegates relation extraction to regex.
    # Entity types are ``unknown`` but predicates ride on the regex layer.
    "gliner": [
        ("unknown", "unknown", "is_a"),
        ("unknown", "unknown", "subset_of"),
        ("unknown", "unknown", "used_for"),
        ("unknown", "unknown", "uses"),
    ],
    # -- llm_extractor.py: predicates are schema-driven; we model the
    # surface as wildcards so the LLM is excluded from local collision
    # analysis. Validation happens via the schema's edge whitelist.
    "llm": [
        ("*", "*", "*"),
    ],
    # -- parser_extractor.py (sv_parser): _make_triple call sites only.
    "sv_parser": [
        ("Module", "Port", "contains"),
        ("Module", "Net", "contains"),
        ("Module", "Variable", "contains"),
        ("Module", "Parameter", "contains"),
        ("Module", "Instance", "contains"),
        ("Module", "Module", "instantiates"),
        ("Module", "Package", "depends_on"),
    ],
    # -- sv_connectivity.py (slang): predicates surveyed lines 291..1063.
    "slang": [
        ("Instance", "Module", "instance_of"),
        ("Instance", "Instance", "part_of"),
        ("Module", "Module", "instantiates"),
        ("Module", "Member", "contains"),  # ports/nets/vars/params
        ("Net", "Port", "drives"),  # also Port->Net for outputs
        ("Port", "Net", "drives"),
        ("Instance", "Parameter", "binds_parameter"),
        ("Module", "ClockDomain", "clocked_by"),
        ("Module", "ResetDomain", "reset_by"),
        ("Module", "SVA_Assertion", "has_assertion"),
        ("SVA_Assertion", "Signal", "references_signal"),
        ("Module", "FSM", "has_fsm"),
        ("FSM", "FSM_State", "has_state"),
        ("FSM_State", "FSM_State", "transitions_to"),
    ],
    # -- python_parser.py
    "python_parser": [
        ("PythonModule", "PythonClass", "contains"),
        ("PythonModule", "PythonFunction", "contains"),
        ("PythonModule", "PythonVariable", "contains"),
        ("PythonModule", "PythonImport", "depends_on"),  # imports at module level
        ("PythonClass", "PythonFunction", "contains"),
        ("PythonClass", "PythonClass", "depends_on"),  # base classes
    ],
    # -- bash_parser.py
    "bash_parser": [
        ("BashScript", "BashFunction", "contains"),
        ("BashScript", "BashVariable", "contains"),
        ("BashScript", "BashScript", "depends_on"),  # sourced files
    ],
    # -- hjson_csr_extractor.py
    "hjson_csr": [
        ("RTL_Module", "CSR_Register", "has_register"),
        ("RTL_Module", "CSR_Field", "has_field"),  # via register chain
        ("CSR_Register", "CSR_Field", "has_field"),
    ],
    # -- markdown_doc_extractor.py
    "markdown_doc": [
        ("Section", "Section", "references"),
        ("Section", "*", "mentions"),
    ],
}


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------


def _flatten_matrix() -> List[Tuple[str, str, str, str]]:
    """Return list of (extractor, src_type, tgt_type, predicate)."""
    rows: List[Tuple[str, str, str, str]] = []
    for extractor, triples in EXTRACTOR_PREDICATE_MATRIX.items():
        for src, tgt, pred in triples:
            # Skip the LLM wildcard row — predicates are schema-driven and
            # validation runs at ingest time, not in this matrix.
            if pred == "*":
                continue
            rows.append((extractor, src, tgt, pred))
    return rows


# Known intra-extractor (source_type, target_type) buckets that emit
# multiple predicates. These are the high-risk extractors: if their
# predicates ever land on the *same concrete* (subject, object) pair,
# DiGraph will drop all but one observation. Each entry must have a
# documented mitigation strategy.
KNOWN_INTRA_EXTRACTOR_COLLISIONS: Dict[Tuple[str, str, str], str] = {
    # regex extractor: free-text pattern matching can in theory match the
    # same (A, B) pair under multiple patterns. Risk is low because each
    # regex matches a different sentence shape ("X is a Y" vs "X uses Y"),
    # but a single sentence containing "X is a Y that uses Y" *would*
    # produce two predicates between (X, Y).
    # Mitigation: the regex extractor should be considered "best effort";
    # losing a parallel predicate is acceptable here because predicates
    # carry low confidence anyway. Re-evaluate after MultiDiGraph migration.
    ("regex", "concept", "concept"): "low-confidence text patterns; tolerated",
    ("gliner", "unknown", "unknown"): "delegates to regex — same risk profile",
}


def test_intra_extractor_collisions_are_only_the_known_ones() -> None:
    """A single extractor emitting multiple predicates between the same
    (source_type, target_type) pair is a DiGraph collapse hazard.

    Slang's ``connects_to`` + ``drives`` shadowing was exactly this class
    of bug. Adding a new collision must be done deliberately: register it
    in ``KNOWN_INTRA_EXTRACTOR_COLLISIONS`` along with a mitigation note.
    """
    new_collisions: List[str] = []
    for extractor, triples in EXTRACTOR_PREDICATE_MATRIX.items():
        seen: Dict[Tuple[str, str], Set[str]] = {}
        for src, tgt, pred in triples:
            if pred == "*":
                continue
            seen.setdefault((src, tgt), set()).add(pred)
        for (src, tgt), preds in seen.items():
            if len(preds) > 1 and (extractor, src, tgt) not in KNOWN_INTRA_EXTRACTOR_COLLISIONS:
                new_collisions.append(
                    f"{extractor}: ({src} -> {tgt}) emits {sorted(preds)}"
                )
    if new_collisions:
        pytest.fail(
            "New intra-extractor predicate collisions detected — DiGraph "
            "will shadow all but one. Either pick a single canonical "
            "predicate, switch the backend to MultiDiGraph, or register "
            "in KNOWN_INTRA_EXTRACTOR_COLLISIONS with a mitigation note:\n"
            + "\n".join(new_collisions)
        )


def test_cross_extractor_collisions_are_documented() -> None:
    """Cross-extractor (source_type, target_type) pairs that emit different
    predicates are flagged here. Some are *expected* and listed in the
    allowed-collisions set; others would surface as new bugs.

    Note that cross-extractor collisions are only a problem when the SAME
    (subject, object) node pair receives both predicates — different
    extractors usually operate on disjoint corpora (Verilog vs Markdown vs
    Python) so the type-overlap is theoretical. Still worth tracking.
    """
    pair_to_preds: Dict[Tuple[str, str], Dict[str, Set[str]]] = {}
    for extractor, src, tgt, pred in _flatten_matrix():
        pair_to_preds.setdefault((src, tgt), {}).setdefault(extractor, set()).add(pred)

    # Same (src, tgt) with different predicates from different extractors.
    cross: List[str] = []
    for (src, tgt), per_extractor in pair_to_preds.items():
        if len(per_extractor) < 2:
            continue
        all_preds = set().union(*per_extractor.values())
        if len(all_preds) > 1:
            cross.append(
                f"({src} -> {tgt}): "
                + ", ".join(
                    f"{e}={sorted(p)}" for e, p in sorted(per_extractor.items())
                )
            )

    # Document any collision below. As of writing, the matrix is clean
    # because each extractor operates on disjoint type namespaces (e.g.
    # PythonClass is unique to python_parser, RTL_Module to hjson_csr).
    # ``concept``/``unknown`` is shared between regex and gliner; their
    # predicates are identical, so no cross-predicate clash arises.
    expected_collisions: Set[str] = set()  # update if a new one is allowed

    unexpected = [c for c in cross if c not in expected_collisions]
    if unexpected:
        pytest.fail(
            "Unexpected cross-extractor predicate collisions:\n"
            + "\n".join(unexpected)
            + "\nIf these are intentional, add them to expected_collisions."
        )


# ---------------------------------------------------------------------------
# Adversarial round-trip tests against the real backend
# ---------------------------------------------------------------------------
#
# These three tests demonstrate the DiGraph collapse hazard with concrete
# upserts. They are marked xfail because the current backend is known to
# lose information in these cases. Once the backend migrates to
# MultiDiGraph (or an equivalent multi-edge store), remove the xfail
# decorators — they will then start passing.


def test_two_predicates_between_same_pair_both_survive_round_trip() -> None:
    backend = NetworkXBackend()
    backend.upsert_entities(
        [
            Entity(name="A", type="concept", sources=["s"]),
            Entity(name="B", type="concept", sources=["s"]),
        ]
    )
    backend.upsert_triples(
        [
            Triple(subject="A", predicate="connects_to", object="B", source="s"),
            Triple(subject="A", predicate="drives", object="B", source="s"),
        ]
    )

    out = backend.get_outgoing_edges("A")
    predicates = {t.predicate for t in out}
    assert {"connects_to", "drives"}.issubset(predicates), (
        f"Expected both predicates queryable, got {predicates}"
    )


def test_same_predicate_two_sources_preserves_both_evidence_spans() -> None:
    backend = NetworkXBackend()
    backend.upsert_entities(
        [
            Entity(name="A", type="concept", sources=["s1"]),
            Entity(name="B", type="concept", sources=["s1"]),
        ]
    )
    backend.upsert_triples(
        [
            Triple(
                subject="A",
                predicate="is_a",
                object="B",
                source="doc1.md",
                evidence_span="A is a B (from doc1)",
            ),
            Triple(
                subject="A",
                predicate="is_a",
                object="B",
                source="doc2.md",
                evidence_span="A is a B (from doc2)",
            ),
        ]
    )

    edge = backend.graph["A"]["B"]["is_a"]
    evidences = edge.get("evidences", [])
    spans = [e.get("evidence_span") for e in evidences]
    assert "A is a B (from doc1)" in spans
    assert "A is a B (from doc2)" in spans


def test_edge_to_phantom_node_creates_well_formed_node_or_errors() -> None:
    """When ``upsert_triples`` references an object that was never
    upserted as an Entity, ``add_edge`` auto-creates the node *with*
    well-formed attrs (type defaulted to "concept", sources populated
    from the triple's source, aliases initialised). A subsequent
    ``add_node`` then merges any additional attrs without clobbering
    the existing edge.
    """
    backend = NetworkXBackend()
    # Upsert an edge whose target ``Phantom`` was never previously declared.
    backend.upsert_triples(
        [
            Triple(
                subject="Known",
                predicate="references",
                object="Phantom",
                source="doc.md",
            )
        ]
    )
    # The node now exists in the graph and is well-formed: type defaulted,
    # sources propagated from the triple, aliases list initialised.
    assert backend.graph.has_node("Phantom")
    stub = backend.graph.nodes["Phantom"]
    assert stub.get("type") == "concept"
    assert stub.get("sources") == ["doc.md"]
    assert stub.get("aliases") == []

    # Now upsert the entity for real — add_node should merge attrs (the
    # source is already present, so the list stays deduplicated).
    backend.add_node(name="Phantom", type="concept", source="doc.md")
    promoted = backend.graph.nodes["Phantom"]
    assert promoted["type"] == "concept"
    assert "doc.md" in promoted["sources"]

    # And the edge survives the promotion.
    out = backend.get_outgoing_edges("Known")
    assert any(t.predicate == "references" and t.object == "Phantom" for t in out)
