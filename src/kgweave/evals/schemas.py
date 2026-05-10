# @summary
# Eval-harness data contracts: QAPair (golden item), EvalResult (per-question
# outcome), AggregateMetrics (corpus-level summary). Pure dataclasses.
# @end-summary
"""Eval-harness data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


__all__ = ["QAPair", "EvalResult", "AggregateMetrics"]


@dataclass
class QAPair:
    """A single golden Q&A item.

    Attributes:
        id: Stable identifier (e.g. ``ibex-001``).
        question: Natural-language question for retrieval.
        gold_entities: Entity names that a correct answer must surface.
        gold_answer: Optional reference answer text (free form).
        category: Coarse-grained tag (``structure``, ``hierarchy``, ``connectivity``,
            ``parameters``, ``architecture``).
        tags: Free-form tags for slicing the eval (e.g. ``instantiates``).
    """

    id: str
    question: str
    gold_entities: List[str] = field(default_factory=list)
    gold_answer: str = ""
    category: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Per-question evaluation outcome."""

    qa_id: str
    predicted_entities: List[str]
    gold_entities: List[str]
    entity_precision: float
    entity_recall: float
    entity_f1: float


@dataclass
class AggregateMetrics:
    """Corpus-level eval summary."""

    num_questions: int
    mean_entity_precision: float
    mean_entity_recall: float
    mean_entity_f1: float
