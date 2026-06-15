"""I8 — read-only enforcement for ``RawCypher``."""

from __future__ import annotations

import pytest

from knowledge_graph.query import (
    BANNED_KEYWORDS,
    RawCypher,
    ReadOnlyViolation,
    assert_read_only,
    compile_intent,
)


@pytest.mark.parametrize("kw", BANNED_KEYWORDS)
def test_every_banned_keyword_is_rejected(kw):
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(f"MATCH (n) {kw} (n)")


@pytest.mark.parametrize("kw", [k.lower() for k in BANNED_KEYWORDS])
def test_banned_keywords_are_case_insensitive(kw):
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(f"MATCH (n) {kw} (n)")


def test_banned_keyword_inside_string_literal_is_allowed():
    # `'CREATE'` is a literal — not a Cypher keyword.
    assert_read_only("MATCH (n) WHERE n.name = 'CREATE' RETURN n")
    assert_read_only('MATCH (n) WHERE n.name = "DELETE foo" RETURN n')


def test_banned_keyword_inside_line_comment_is_allowed():
    assert_read_only("MATCH (n) RETURN n // CREATE me later")


def test_banned_keyword_inside_block_comment_is_allowed():
    assert_read_only("MATCH (n) /* DROP this */ RETURN n")


def test_banned_keyword_as_identifier_substring_is_allowed():
    # 'CREATED_AT' is a property name — not the CREATE keyword.
    assert_read_only("MATCH (n) WHERE n.CREATED_AT > 0 RETURN n")


def test_set_buried_in_case_expression_is_still_rejected():
    bad = "MATCH (n) RETURN CASE WHEN n.x = 1 THEN n SET n.bad=1 ELSE n END"
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(bad)


def test_compile_raw_param_value_with_banned_keyword_not_rejected():
    # Param dict is out-of-band; banned content there must not trigger.
    intent = RawCypher(
        cypher="MATCH (n:Node) WHERE n.name = $name RETURN n.id",
        parameters={"name": "DELETE FROM Node"},
    )
    cypher, params = compile_intent(intent)
    assert cypher == "MATCH (n:Node) WHERE n.name = $name RETURN n.id"
    assert params == {"name": "DELETE FROM Node"}


def test_assert_read_only_returns_none_on_pure_read():
    assert assert_read_only("MATCH (n:Node) RETURN n.id LIMIT 10") is None


def test_call_keyword_is_rejected_by_default():
    with pytest.raises(ReadOnlyViolation):
        assert_read_only("CALL some_procedure()")
