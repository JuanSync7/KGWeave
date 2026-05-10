# @summary
# YAML loader for the golden Q&A set used by the eval harness. Top-level
# format: ``questions: [{id, question, gold_entities, gold_answer?, category?, tags?}]``.
# Raises ValueError with the offending key in the message on schema drift.
# @end-summary
"""YAML loader for golden Q&A sets."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Union

import yaml

from kgweave.evals.schemas import QAPair


__all__ = ["load_qa_set"]


def load_qa_set(path: Union[str, Path]) -> List[QAPair]:
    """Load a list of ``QAPair`` from a YAML file.

    Args:
        path: Filesystem path to the YAML file.

    Raises:
        ValueError: If the YAML is missing the ``questions`` key or any item
            lacks a required field (``id`` or ``question``).
    """
    raw: Any = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or "questions" not in raw:
        raise ValueError(f"YAML at {path} missing top-level 'questions' key")

    items = raw["questions"] or []
    out: List[QAPair] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"questions[{i}] is not a mapping")
        if "id" not in item:
            raise ValueError(f"questions[{i}] missing required 'id' field")
        if "question" not in item:
            raise ValueError(f"questions[{i}] missing required 'question' field")
        out.append(QAPair(
            id=str(item["id"]),
            question=str(item["question"]),
            gold_entities=list(item.get("gold_entities", []) or []),
            gold_answer=str(item.get("gold_answer", "") or ""),
            category=str(item.get("category", "") or ""),
            tags=list(item.get("tags", []) or []),
        ))
    return out
