# @summary
# KGWeave eval harness: golden Q&A driven entity-recall benchmarking.
# Public surface: QAPair, EvalResult, AggregateMetrics, entity_prf, aggregate, load_qa_set.
# @end-summary
"""Eval harness for KGWeave (entity-level recall against a golden Q&A set)."""

from kgweave.evals.schemas import QAPair, EvalResult, AggregateMetrics
from kgweave.evals.metrics import entity_prf, aggregate
from kgweave.evals.loader import load_qa_set
from kgweave.evals.runner import run_eval, Predictor

__all__ = [
    "QAPair",
    "EvalResult",
    "AggregateMetrics",
    "entity_prf",
    "aggregate",
    "load_qa_set",
    "run_eval",
    "Predictor",
]
