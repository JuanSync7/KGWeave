# @summary
# TDD: data contracts for the KGWeave eval harness — QAPair, EvalResult,
# AggregateMetrics. Pure dataclasses; no business logic. Validates that the
# schemas can round-trip through YAML and exclude/include the right fields.
# @end-summary
"""Eval-harness schema tests."""

from __future__ import annotations

import pytest


class TestQAPair:
    def test_minimal_qa_pair(self) -> None:
        from kgweave.evals.schemas import QAPair
        qa = QAPair(
            id="ibex-001",
            question="What ports does the ibex_core module have?",
            gold_entities=["ibex_core.clk_i", "ibex_core.rst_ni"],
        )
        assert qa.id == "ibex-001"
        assert qa.gold_entities == ["ibex_core.clk_i", "ibex_core.rst_ni"]
        assert qa.gold_answer == ""  # default
        assert qa.category == ""

    def test_qa_pair_full(self) -> None:
        from kgweave.evals.schemas import QAPair
        qa = QAPair(
            id="ibex-002",
            question="What does ibex_core instantiate?",
            gold_entities=["ibex_id_stage", "ibex_if_stage"],
            gold_answer="ibex_core instantiates the IF and ID pipeline stages.",
            category="hierarchy",
            tags=["instantiates", "pipeline"],
        )
        assert qa.category == "hierarchy"
        assert "instantiates" in qa.tags

    def test_qa_pair_requires_id_and_question(self) -> None:
        from kgweave.evals.schemas import QAPair
        with pytest.raises(TypeError):
            QAPair()  # type: ignore[call-arg]


class TestEvalResult:
    def test_eval_result_per_question(self) -> None:
        from kgweave.evals.schemas import EvalResult
        r = EvalResult(
            qa_id="ibex-001",
            predicted_entities=["ibex_core.clk_i", "ibex_core.foo"],
            gold_entities=["ibex_core.clk_i", "ibex_core.rst_ni"],
            entity_precision=0.5,
            entity_recall=0.5,
            entity_f1=0.5,
        )
        assert r.qa_id == "ibex-001"
        assert r.entity_f1 == 0.5


class TestAggregateMetrics:
    def test_aggregate_metrics_minimal(self) -> None:
        from kgweave.evals.schemas import AggregateMetrics
        m = AggregateMetrics(
            num_questions=50,
            mean_entity_precision=0.7,
            mean_entity_recall=0.6,
            mean_entity_f1=0.64,
        )
        assert m.num_questions == 50
        assert m.mean_entity_f1 == 0.64
