# @summary
# Eval runner: applies a user-supplied predictor to each QAPair, computes
# per-question entity P/R/F1, and aggregates. The predictor signature is
# ``Callable[[QAPair], Iterable[str]]`` so the harness stays decoupled from
# any specific retrieval backend (KG expansion, plain vector search, etc).
# @end-summary
"""Eval runner — predictor-agnostic."""

from __future__ import annotations

import logging
from typing import Callable, Iterable, List, Tuple

from kgweave.evals.metrics import aggregate, entity_prf
from kgweave.evals.schemas import AggregateMetrics, EvalResult, QAPair


__all__ = ["run_eval", "Predictor"]

logger = logging.getLogger("kgweave.evals.runner")

Predictor = Callable[[QAPair], Iterable[str]]


def run_eval(
    qas: Iterable[QAPair],
    predictor: Predictor,
) -> Tuple[List[EvalResult], AggregateMetrics]:
    """Run ``predictor`` over every QAPair and return per-Q + aggregate metrics.

    Predictor failures are caught per question — the run continues and the
    failed question is recorded with an empty prediction (F1=0).
    """
    results: List[EvalResult] = []
    for qa in qas:
        try:
            predicted = list(predictor(qa))
        except Exception as exc:  # noqa: BLE001 — eval harness must be tolerant
            logger.warning("predictor failed on %s: %s", qa.id, exc)
            predicted = []
        p, r, f = entity_prf(predicted, qa.gold_entities)
        results.append(EvalResult(
            qa_id=qa.id,
            predicted_entities=predicted,
            gold_entities=list(qa.gold_entities),
            entity_precision=p,
            entity_recall=r,
            entity_f1=f,
        ))
    return results, aggregate(results)
