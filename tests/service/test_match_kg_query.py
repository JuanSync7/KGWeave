"""Unit tests for DefaultKGQueryService.match_kg_query.

Covers the word-level match path, the top-N fallback when nothing matches,
and the empty-index edge case.
"""

from __future__ import annotations

from collections import defaultdict
from unittest.mock import patch

from kgweave.knowledge_graph.query.term_index import KGTermIndex
from kgweave.service.query_service import DefaultKGQueryService


def _index(terms: list[str], word_index: dict[str, list[str]]) -> KGTermIndex:
    idx = KGTermIndex(terms=terms, word_index=defaultdict(list))
    for k, v in word_index.items():
        idx.word_index[k] = list(v)
    return idx


def test_match_returns_word_level_hits():
    index = _index(
        terms=["alpha-mod", "beta-mod", "gamma-mod"],
        word_index={"alpha": ["alpha-mod"], "beta": ["beta-mod"]},
    )
    with patch("kgweave.knowledge_graph.get_term_index", return_value=index):
        result = DefaultKGQueryService().match_kg_query("alpha goes beta", max_terms=10)
    assert set(result.matched) == {"alpha-mod", "beta-mod"}
    assert result.used_fallback is False


def test_match_falls_back_to_top_n_when_no_word_hit():
    index = _index(
        terms=["alpha-mod", "beta-mod", "gamma-mod"],
        word_index={"alpha": ["alpha-mod"]},
    )
    with patch("kgweave.knowledge_graph.get_term_index", return_value=index):
        result = DefaultKGQueryService().match_kg_query("zeta omicron", max_terms=2)
    assert result.matched == ["alpha-mod", "beta-mod"]
    assert result.used_fallback is True


def test_match_returns_empty_when_index_empty():
    index = _index(terms=[], word_index={})
    with patch("kgweave.knowledge_graph.get_term_index", return_value=index):
        result = DefaultKGQueryService().match_kg_query("anything", max_terms=5)
    assert result.matched == []
    assert result.used_fallback is False


def test_match_respects_max_terms_cap():
    index = _index(
        terms=["a", "b", "c"],
        word_index={"foo": ["a", "b", "c", "d", "e"]},
    )
    with patch("kgweave.knowledge_graph.get_term_index", return_value=index):
        result = DefaultKGQueryService().match_kg_query("foo", max_terms=2)
    assert len(result.matched) == 2
    assert result.used_fallback is False


def test_match_skips_short_words():
    index = _index(
        terms=["alpha-mod"],
        word_index={"is": ["alpha-mod"], "alpha": ["alpha-mod"]},
    )
    # "is" is 2 chars and would match if not filtered; min_word_length=3 by default.
    with patch("kgweave.knowledge_graph.get_term_index", return_value=index):
        result = DefaultKGQueryService().match_kg_query("is the", max_terms=5)
    assert result.matched == ["alpha-mod"]  # via fallback (no long words matched)
    assert result.used_fallback is True
