# @summary
# TDD: entity-level precision/recall/F1 for the eval harness. Set-based
# (order-insensitive, dedupes). Edge cases: empty gold, empty prediction,
# perfect match, completely-disjoint sets.
# @end-summary
"""Eval-harness metric tests."""

from __future__ import annotations

import pytest


class TestEntityF1:
    def test_perfect_match_is_1(self) -> None:
        from kgweave.evals.metrics import entity_prf
        p, r, f = entity_prf(predicted={"a", "b"}, gold={"a", "b"})
        assert (p, r, f) == (1.0, 1.0, 1.0)

    def test_disjoint_is_0(self) -> None:
        from kgweave.evals.metrics import entity_prf
        p, r, f = entity_prf(predicted={"x"}, gold={"a", "b"})
        assert (p, r, f) == (0.0, 0.0, 0.0)

    def test_partial_overlap(self) -> None:
        from kgweave.evals.metrics import entity_prf
        # tp=1 (a), fp=1 (c), fn=1 (b)
        p, r, f = entity_prf(predicted={"a", "c"}, gold={"a", "b"})
        assert p == pytest.approx(0.5)
        assert r == pytest.approx(0.5)
        assert f == pytest.approx(0.5)

    def test_empty_prediction_is_0_recall(self) -> None:
        from kgweave.evals.metrics import entity_prf
        p, r, f = entity_prf(predicted=set(), gold={"a"})
        assert p == 0.0  # convention: no predictions = 0 precision
        assert r == 0.0
        assert f == 0.0

    def test_empty_gold_returns_neutral(self) -> None:
        # Convention: undefined recall when gold is empty — return 0/0/0
        # rather than NaN so aggregate means stay numeric.
        from kgweave.evals.metrics import entity_prf
        p, r, f = entity_prf(predicted={"a"}, gold=set())
        assert (p, r, f) == (0.0, 0.0, 0.0)

    def test_both_empty_returns_zeros(self) -> None:
        from kgweave.evals.metrics import entity_prf
        assert entity_prf(predicted=set(), gold=set()) == (0.0, 0.0, 0.0)

    def test_accepts_lists_too(self) -> None:
        from kgweave.evals.metrics import entity_prf
        p, r, f = entity_prf(predicted=["a", "a", "b"], gold=["a", "b"])
        # Dedupes silently — list inputs treated as sets.
        assert (p, r, f) == (1.0, 1.0, 1.0)


class TestAggregate:
    def test_aggregate_mean_over_results(self) -> None:
        from kgweave.evals.metrics import aggregate
        from kgweave.evals.schemas import EvalResult
        results = [
            EvalResult(qa_id="1", predicted_entities=[], gold_entities=[],
                       entity_precision=1.0, entity_recall=1.0, entity_f1=1.0),
            EvalResult(qa_id="2", predicted_entities=[], gold_entities=[],
                       entity_precision=0.0, entity_recall=0.0, entity_f1=0.0),
        ]
        agg = aggregate(results)
        assert agg.num_questions == 2
        assert agg.mean_entity_precision == pytest.approx(0.5)
        assert agg.mean_entity_recall == pytest.approx(0.5)
        assert agg.mean_entity_f1 == pytest.approx(0.5)

    def test_aggregate_empty_returns_zeros(self) -> None:
        from kgweave.evals.metrics import aggregate
        agg = aggregate([])
        assert agg.num_questions == 0
        assert agg.mean_entity_f1 == 0.0
