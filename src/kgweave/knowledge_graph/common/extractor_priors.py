# @summary
# Extractor-class confidence priors and combination rule for triple provenance.
# Each extractor reports a hardcoded prior reflecting its trustworthiness;
# when two extractors emit the same triple, confidences combine via the
# noisy-OR rule: c = 1 - (1 - c1) * (1 - c2). Commutative and associative.
# Exports: EXTRACTOR_CONFIDENCE, confidence_for, combine_confidence
# @end-summary
"""Confidence priors per extractor class and triple-merge combination rule."""

from __future__ import annotations

__all__ = ["EXTRACTOR_CONFIDENCE", "confidence_for", "combine_confidence"]


# Hardcoded per-extractor priors. Higher = more trusted.
# - 1.0  : deterministic parsers / elaborators that read structured source
# - 0.9  : pattern-matching extractors (regex)
# - 0.8  : NER models with reasonable but imperfect calibration
# - 0.6  : LLM-based extractors (poorly calibrated, hallucination-prone)
EXTRACTOR_CONFIDENCE: dict[str, float] = {
    # Deterministic
    "sv_parser": 1.0,
    "slang": 1.0,
    "sv_connectivity": 1.0,
    "python_parser": 1.0,
    "bash_parser": 1.0,
    # Pattern-based
    "regex": 0.9,
    # NER
    "gliner": 0.8,
    # LLM
    "llm": 0.6,
}

# Conservative fallback for extractors not in the map.
_DEFAULT_CONFIDENCE = 0.5


def confidence_for(extractor_name: str) -> float:
    """Return the confidence prior for a given extractor name.

    Args:
        extractor_name: Identifier from ``Triple.extractor_source``.

    Returns:
        Prior in [0, 1]. Unknown extractors get the conservative default.
    """
    if not extractor_name:
        return _DEFAULT_CONFIDENCE
    return EXTRACTOR_CONFIDENCE.get(extractor_name, _DEFAULT_CONFIDENCE)


def combine_confidence(c1: float, c2: float) -> float:
    """Combine two independent confidence estimates via noisy-OR.

    ``c = 1 - (1 - c1) * (1 - c2)``

    Two extractors that agree on a triple raise overall confidence above
    either individual estimate. The rule is commutative and associative,
    so the order of merges does not matter.

    Args:
        c1: First confidence in [0, 1].
        c2: Second confidence in [0, 1].

    Returns:
        Combined confidence in [0, 1].
    """
    return 1.0 - (1.0 - c1) * (1.0 - c2)
