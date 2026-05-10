# @summary
# TDD: per-question eval runner. Given an entity-prediction callable + a list
# of QAPair, it runs the predictor for each Q and returns EvalResults +
# AggregateMetrics. The predictor is injected so the harness is decoupled
# from any specific KG retrieval pipeline.
# @end-summary
"""Tests for the eval runner (decoupled from the live retrieval stack)."""

from __future__ import annotations

import pytest


class TestRunner:
    def test_runs_each_qa_through_predictor(self) -> None:
        from kgweave.evals.runner import run_eval
        from kgweave.evals.schemas import QAPair

        qas = [
            QAPair(id="a", question="?", gold_entities=["x", "y"]),
            QAPair(id="b", question="?", gold_entities=["m"]),
        ]
        # Predictor returns gold for the first Q, miss for the second.
        def predictor(qa: QAPair) -> list[str]:
            return {"a": ["x", "y"], "b": ["wrong"]}[qa.id]

        results, agg = run_eval(qas, predictor)
        assert [r.qa_id for r in results] == ["a", "b"]
        assert results[0].entity_f1 == pytest.approx(1.0)
        assert results[1].entity_f1 == pytest.approx(0.0)
        assert agg.num_questions == 2
        assert agg.mean_entity_f1 == pytest.approx(0.5)

    def test_predictor_exception_recorded_as_zero(self) -> None:
        from kgweave.evals.runner import run_eval
        from kgweave.evals.schemas import QAPair

        qas = [QAPair(id="a", question="?", gold_entities=["x"])]
        def predictor(qa: QAPair) -> list[str]:
            raise RuntimeError("boom")

        results, agg = run_eval(qas, predictor)
        # Failure → empty prediction → zero metrics, but the run continues.
        assert len(results) == 1
        assert results[0].predicted_entities == []
        assert results[0].entity_f1 == 0.0
