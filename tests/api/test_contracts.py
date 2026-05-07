"""Schema-level contract tests for the HTTP wire models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kgweave.contracts.http import (
    ExpandRequest,
    PathRequest,
    TermMatchRequest,
)


def test_expand_request_rejects_empty_query():
    with pytest.raises(ValidationError):
        ExpandRequest(query="")


def test_expand_request_clamps_depth_range():
    with pytest.raises(ValidationError):
        ExpandRequest(query="hi", depth=0)
    with pytest.raises(ValidationError):
        ExpandRequest(query="hi", depth=11)
    assert ExpandRequest(query="hi", depth=3).depth == 3


def test_expand_request_forbids_extras():
    with pytest.raises(ValidationError):
        ExpandRequest(query="hi", unknown=True)  # type: ignore[call-arg]


def test_term_match_request_requires_words():
    with pytest.raises(ValidationError):
        TermMatchRequest(words=[])


def test_path_request_requires_pattern():
    with pytest.raises(ValidationError):
        PathRequest(seed_entity="alpha", patterns=[])
    PathRequest(seed_entity="alpha", patterns=[["instantiates"]])
