"""Tests that the NetworkXBackend preserves per-observation evidence after the
MultiDiGraph migration.

Design contract (decided when migrating from DiGraph to MultiDiGraph):

* Edges are keyed by predicate. Two upserts of the same (subj, pred, obj)
  collapse onto a single keyed edge but ACCUMULATE their evidence into an
  ``evidences`` list of dicts (each dict carries ``evidence_span``,
  ``chunk_id``, ``extracted_at``, ``source``).
* Two upserts of (subj, pred1, obj) and (subj, pred2, obj) result in TWO
  parallel edges in the multigraph (different keys).
"""
from __future__ import annotations

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Entity, Triple


def test_same_triple_two_upserts_accumulate_evidences() -> None:
    """Same (subj, pred, obj), different evidence_span/chunk_id → both survive."""
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
                predicate="related_to",
                object="B",
                source="doc1.md",
                evidence_span="A is related to B (doc1)",
                chunk_id="c1",
            ),
            Triple(
                subject="A",
                predicate="related_to",
                object="B",
                source="doc2.md",
                evidence_span="A connects to B (doc2)",
                chunk_id="c2",
            ),
        ]
    )

    # Inspect via the multigraph edge store directly.
    edge_data = backend.graph["A"]["B"]["related_to"]
    evidences = edge_data.get("evidences", [])
    spans = [e.get("evidence_span") for e in evidences]
    chunks = [e.get("chunk_id") for e in evidences]
    assert "A is related to B (doc1)" in spans
    assert "A connects to B (doc2)" in spans
    assert "c1" in chunks
    assert "c2" in chunks

    # And via the public query API: one Triple per edge-key (deduped on
    # predicate). The returned Triple's evidence_span should be one of the
    # observations (latest), and weight should reflect frequency.
    out = backend.get_outgoing_edges("A")
    related = [t for t in out if t.predicate == "related_to"]
    assert len(related) == 1
    assert related[0].weight >= 2.0


def test_two_predicates_yield_two_parallel_edges() -> None:
    """Different predicates between the same pair must NOT collapse."""
    backend = NetworkXBackend()
    backend.upsert_entities(
        [
            Entity(name="A", type="concept", sources=["s"]),
            Entity(name="B", type="concept", sources=["s"]),
        ]
    )
    backend.upsert_triples(
        [
            Triple(subject="A", predicate="is_a", object="B", source="s",
                   evidence_span="A is a B"),
            Triple(subject="A", predicate="subset_of", object="B", source="s",
                   evidence_span="A is a subset of B"),
        ]
    )

    out = backend.get_outgoing_edges("A")
    preds = {t.predicate for t in out}
    assert {"is_a", "subset_of"}.issubset(preds)

    # Both keyed edges should be queryable in the underlying multigraph.
    keys = set(backend.graph["A"]["B"].keys())
    assert {"is_a", "subset_of"}.issubset(keys)
