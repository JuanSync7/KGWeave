# @summary
# TDD: per-triple provenance — confidence, evidence_span, chunk_id, extracted_at.
# Also covers extractor-class confidence priors and the agreement-bump merge:
# combine_confidence(c1, c2) = 1 - (1-c1)*(1-c2)
# @end-summary
"""Tests for triple-level provenance fields and extractor-class confidence priors."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kgweave.knowledge_graph.common.schemas import Triple
from kgweave.knowledge_graph.common.extractor_priors import (
    EXTRACTOR_CONFIDENCE,
    combine_confidence,
    confidence_for,
)
from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend


# -----------------------------------------------------------------------------
# Triple dataclass: new provenance fields
# -----------------------------------------------------------------------------


class TestTripleProvenanceFields:
    def test_triple_has_confidence_default_1_0(self) -> None:
        t = Triple(subject="a", predicate="rel", object="b")
        assert t.confidence == 1.0

    def test_triple_accepts_confidence(self) -> None:
        t = Triple(subject="a", predicate="rel", object="b", confidence=0.6)
        assert t.confidence == 0.6

    def test_triple_has_evidence_span_default_empty(self) -> None:
        t = Triple(subject="a", predicate="rel", object="b")
        assert t.evidence_span == ""

    def test_triple_accepts_evidence_span(self) -> None:
        t = Triple(
            subject="a",
            predicate="rel",
            object="b",
            evidence_span="cpu connects to memory via AXI4",
        )
        assert t.evidence_span == "cpu connects to memory via AXI4"

    def test_triple_has_chunk_id_default_empty(self) -> None:
        t = Triple(subject="a", predicate="rel", object="b")
        assert t.chunk_id == ""

    def test_triple_accepts_chunk_id(self) -> None:
        t = Triple(subject="a", predicate="rel", object="b", chunk_id="doc1#3")
        assert t.chunk_id == "doc1#3"

    def test_triple_has_extracted_at_default_none(self) -> None:
        t = Triple(subject="a", predicate="rel", object="b")
        assert t.extracted_at is None

    def test_triple_accepts_extracted_at(self) -> None:
        ts = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
        t = Triple(subject="a", predicate="rel", object="b", extracted_at=ts)
        assert t.extracted_at == ts


# -----------------------------------------------------------------------------
# Extractor priors: confidence per extractor class
# -----------------------------------------------------------------------------


class TestExtractorPriors:
    def test_deterministic_extractors_are_1_0(self) -> None:
        for name in ("sv_parser", "slang", "python_parser", "bash_parser",
                    "sv_connectivity"):
            assert EXTRACTOR_CONFIDENCE[name] == 1.0, name

    def test_regex_is_0_9(self) -> None:
        assert EXTRACTOR_CONFIDENCE["regex"] == 0.9

    def test_gliner_is_0_8(self) -> None:
        assert EXTRACTOR_CONFIDENCE["gliner"] == 0.8

    def test_llm_is_0_6(self) -> None:
        assert EXTRACTOR_CONFIDENCE["llm"] == 0.6

    def test_confidence_for_known_extractor(self) -> None:
        assert confidence_for("sv_parser") == 1.0
        assert confidence_for("llm") == 0.6

    def test_confidence_for_unknown_extractor_returns_default(self) -> None:
        # Unknown extractor → conservative default (0.5)
        assert confidence_for("__nonexistent__") == 0.5

    def test_confidence_for_empty_string_returns_default(self) -> None:
        assert confidence_for("") == 0.5


# -----------------------------------------------------------------------------
# Agreement bump: combine_confidence
# -----------------------------------------------------------------------------


class TestCombineConfidence:
    def test_combine_two_certain_extractors_caps_at_1(self) -> None:
        assert combine_confidence(1.0, 1.0) == 1.0

    def test_combine_two_uncertain_increases(self) -> None:
        # 1 - (1-0.6)*(1-0.6) = 1 - 0.16 = 0.84
        assert combine_confidence(0.6, 0.6) == pytest.approx(0.84)

    def test_combine_high_low(self) -> None:
        # 1 - (1-0.9)*(1-0.6) = 1 - 0.04 = 0.96
        assert combine_confidence(0.9, 0.6) == pytest.approx(0.96)

    def test_combine_is_commutative(self) -> None:
        assert combine_confidence(0.7, 0.3) == pytest.approx(
            combine_confidence(0.3, 0.7)
        )

    def test_combine_with_zero_returns_other(self) -> None:
        assert combine_confidence(0.0, 0.6) == pytest.approx(0.6)

    def test_combine_associative_three_extractors(self) -> None:
        # (a then b) then c == a then (b then c)
        a, b, c = 0.6, 0.8, 0.9
        left = combine_confidence(combine_confidence(a, b), c)
        right = combine_confidence(a, combine_confidence(b, c))
        assert left == pytest.approx(right)


# -----------------------------------------------------------------------------
# Backend integration: confidence persists and combines on duplicate edges
# -----------------------------------------------------------------------------


class TestBackendConfidenceMerge:
    def test_single_triple_persists_confidence(self) -> None:
        backend = NetworkXBackend()
        backend.upsert_entities([])  # no entities needed; add_edge auto-adds nodes
        backend.upsert_triples([
            Triple(
                subject="cpu", predicate="connects_to", object="mem",
                source="doc1", confidence=0.6, extractor_source="llm",
            ),
        ])
        edges = backend.get_outgoing_edges("cpu")
        assert len(edges) == 1
        # Edge data should expose confidence, not just weight
        edge_attrs = backend.graph["cpu"]["mem"]["connects_to"]
        assert edge_attrs["confidence"] == pytest.approx(0.6)

    def test_duplicate_triple_combines_confidence(self) -> None:
        backend = NetworkXBackend()
        backend.upsert_triples([
            Triple(
                subject="cpu", predicate="connects_to", object="mem",
                source="doc1", confidence=0.6, extractor_source="llm",
            ),
        ])
        backend.upsert_triples([
            Triple(
                subject="cpu", predicate="connects_to", object="mem",
                source="doc2", confidence=0.9, extractor_source="regex",
            ),
        ])
        edge_attrs = backend.graph["cpu"]["mem"]["connects_to"]
        # 1 - (1-0.6)*(1-0.9) = 0.96
        assert edge_attrs["confidence"] == pytest.approx(0.96)

    def test_upsert_resolves_confidence_from_extractor_source(self) -> None:
        # Triple with extractor_source but no explicit confidence — the
        # backend should fill confidence from the extractor prior so
        # extractor authors don't need to know about confidence at all.
        backend = NetworkXBackend()
        backend.upsert_triples([
            Triple(
                subject="cpu", predicate="connects_to", object="mem",
                source="doc1", extractor_source="llm",  # confidence default 1.0
            ),
        ])
        edge_attrs = backend.graph["cpu"]["mem"]["connects_to"]
        # llm prior is 0.6 → backend should override the 1.0 default
        assert edge_attrs["confidence"] == pytest.approx(0.6)

    def test_upsert_unknown_extractor_uses_default_prior(self) -> None:
        backend = NetworkXBackend()
        backend.upsert_triples([
            Triple(
                subject="a", predicate="r", object="b",
                extractor_source="__nonexistent__",
            ),
        ])
        edge_attrs = backend.graph["a"]["b"]["r"]
        assert edge_attrs["confidence"] == pytest.approx(0.5)

    def test_upsert_no_extractor_source_keeps_explicit_confidence(self) -> None:
        # Manual triple construction (e.g. tests) without extractor_source —
        # the explicit confidence on the Triple should pass through.
        backend = NetworkXBackend()
        backend.upsert_triples([
            Triple(
                subject="a", predicate="r", object="b", confidence=0.42,
            ),
        ])
        edge_attrs = backend.graph["a"]["b"]["r"]
        assert edge_attrs["confidence"] == pytest.approx(0.42)

    def test_evidence_span_preserved_on_first_upsert(self) -> None:
        backend = NetworkXBackend()
        backend.upsert_triples([
            Triple(
                subject="cpu", predicate="connects_to", object="mem",
                source="doc1", confidence=0.6,
                evidence_span="cpu_core talks to mem_ctrl over AXI",
                chunk_id="doc1#3",
            ),
        ])
        edge_attrs = backend.graph["cpu"]["mem"]["connects_to"]
        assert edge_attrs["evidence_span"] == "cpu_core talks to mem_ctrl over AXI"
        assert edge_attrs["chunk_id"] == "doc1#3"
