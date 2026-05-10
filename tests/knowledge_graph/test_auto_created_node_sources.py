"""Tests that auto-created endpoint nodes (created via add_edge) inherit the
source of the triple that introduced them.

Regression: nodes were rendered as ``Mentions: 1, Sources: N/A`` because
``add_edge`` did not propagate the triple's source onto the auto-created
endpoint node attrs.
"""

from __future__ import annotations

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple


def test_add_edge_propagates_source_to_auto_created_endpoints():
    backend = NetworkXBackend()
    backend.upsert_triples(
        [Triple(subject="A", predicate="related_to", object="B", source="file.py")]
    )

    a = backend.get_entity("A")
    b = backend.get_entity("B")
    assert a is not None and b is not None
    assert a.sources == ["file.py"]
    assert b.sources == ["file.py"]


def test_add_edge_accumulates_sources_across_triples():
    backend = NetworkXBackend()
    backend.upsert_triples(
        [
            Triple(subject="A", predicate="p1", object="B", source="f1.py"),
            Triple(subject="A", predicate="p2", object="B", source="f2.py"),
        ]
    )

    a = backend.get_entity("A")
    assert a is not None
    assert set(a.sources) == {"f1.py", "f2.py"}
    b = backend.get_entity("B")
    assert b is not None
    assert set(b.sources) == {"f1.py", "f2.py"}


def test_explicit_upsert_after_auto_create_merges_sources():
    backend = NetworkXBackend()
    backend.upsert_triples(
        [Triple(subject="A", predicate="p", object="B", source="f.py")]
    )
    backend.upsert_entities(
        [Entity(name="A", type="concept", sources=["f2.py"])]
    )

    a = backend.get_entity("A")
    assert a is not None
    assert set(a.sources) == {"f.py", "f2.py"}
