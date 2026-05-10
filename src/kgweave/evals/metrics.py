# @summary
# Set-based entity precision/recall/F1 + corpus-level aggregation. Empty
# inputs return zeros (rather than NaN) so means stay numeric.
# @end-summary
"""Entity-level precision / recall / F1 metrics."""

from __future__ import annotations

from typing import Iterable, Tuple

from kgweave.evals.schemas import AggregateMetrics, EvalResult


__all__ = ["entity_prf", "aggregate"]


def entity_prf(
    predicted: Iterable[str], gold: Iterable[str]
) -> Tuple[float, float, float]:
    """Compute set-based precision, recall, F1.

    Args:
        predicted: Iterable of predicted entity names (deduped).
        gold: Iterable of gold entity names (deduped).

    Returns:
        ``(precision, recall, f1)``. All zero when either set is empty.
    """
    p_set = set(predicted)
    g_set = set(gold)

    if not p_set or not g_set:
        return 0.0, 0.0, 0.0

    tp = len(p_set & g_set)
    if tp == 0:
        return 0.0, 0.0, 0.0

    precision = tp / len(p_set)
    recall = tp / len(g_set)
    f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def aggregate(results: Iterable[EvalResult]) -> AggregateMetrics:
    """Mean precision / recall / F1 across per-question results."""
    rs = list(results)
    n = len(rs)
    if n == 0:
        return AggregateMetrics(0, 0.0, 0.0, 0.0)
    return AggregateMetrics(
        num_questions=n,
        mean_entity_precision=sum(r.entity_precision for r in rs) / n,
        mean_entity_recall=sum(r.entity_recall for r in rs) / n,
        mean_entity_f1=sum(r.entity_f1 for r in rs) / n,
    )
