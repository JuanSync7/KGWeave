# @summary
# Tests for cross-layer fusion in TestplanExtractor:
# (1) Testpoint.desc / Covergroup.desc prose-mention scanning that emits
# `mentions` edges to known RTL entities, and (2) SVA-name normalization
# that lets a testplan ``tests`` reference fuse to an OpenTitan-style
# assertion entity (``A_<thing>_<suffix>`` / ``<thing>_a``) via a
# `covers` edge even when the names don't match exactly.
# @end-summary
"""TDD coverage for testplan desc-mentions and SVA-name normalization."""

from __future__ import annotations

from kgweave.knowledge_graph.extraction.testplan_extractor import (
    TestplanExtractor,
    TESTPLAN_SOURCE,
)


def _make(known=None) -> TestplanExtractor:
    return TestplanExtractor(known_entity_names=known or [])


# -- Goal #1: desc prose-mention extraction ---------------------------------


def test_desc_mentions_emitted_for_known_module() -> None:
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: smoke
          desc: '''Exercises the cipher_core FSM under back-to-back input.'''
          stage: V1
          tests: ["aes_smoke"]
        }
      ]
    }
    """
    res = _make(known=["cipher_core"]).extract(
        hjson_text, source="aes_testplan.hjson"
    )
    mentions = [t for t in res.triples if t.predicate == "mentions"]
    assert any(
        t.subject == "aes_testplan.smoke" and t.object == "cipher_core"
        for t in mentions
    ), f"expected smoke -> cipher_core mention, got: {mentions}"


def test_desc_mentions_skips_backtick_spans() -> None:
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: smoke
          desc: '''Test `cipher_core` reset behaviour.'''
          stage: V1
          tests: ["aes_smoke"]
        }
      ]
    }
    """
    res = _make(known=["cipher_core"]).extract(
        hjson_text, source="aes_testplan.hjson"
    )
    mentions = [t for t in res.triples if t.predicate == "mentions"]
    assert not any(t.object == "cipher_core" for t in mentions), (
        f"backtick-wrapped match should be skipped, got: {mentions}"
    )


def test_desc_mentions_evidence_span() -> None:
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: smoke
          desc: '''Exercises the cipher_core FSM under load.'''
          stage: V1
          tests: ["aes_smoke"]
        }
      ]
    }
    """
    res = _make(known=["cipher_core"]).extract(
        hjson_text, source="aes_testplan.hjson"
    )
    mentions = [t for t in res.triples
                if t.predicate == "mentions" and t.object == "cipher_core"]
    assert mentions, "expected at least one mentions edge"
    assert "cipher_core" in mentions[0].evidence_span, (
        f"evidence span should contain match context, got: "
        f"{mentions[0].evidence_span!r}"
    )


def test_desc_mentions_case_insensitive() -> None:
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: smoke
          desc: '''Exercises the Cipher_Core FSM.'''
          stage: V1
          tests: ["aes_smoke"]
        }
      ]
    }
    """
    res = _make(known=["cipher_core"]).extract(
        hjson_text, source="aes_testplan.hjson"
    )
    mentions = [t for t in res.triples if t.predicate == "mentions"]
    assert any(t.object == "cipher_core" for t in mentions), (
        f"case-insensitive match should fire, got: {mentions}"
    )


def test_desc_mentions_skips_self_reference() -> None:
    # The testpoint canonical is "aes_testplan.smoke"; suppose a known
    # entity has the same canonical name. Don't emit a self-edge.
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: smoke
          desc: '''The smoke test exercises smoke paths.'''
          stage: V1
          tests: ["aes_smoke"]
        }
      ]
    }
    """
    res = _make(known=["aes_testplan.smoke", "smoke"]).extract(
        hjson_text, source="aes_testplan.hjson"
    )
    mentions = [t for t in res.triples if t.predicate == "mentions"]
    assert all(t.subject != t.object for t in mentions), (
        f"no self-edge should be emitted, got: {mentions}"
    )


def test_covergroup_desc_mentions_emitted() -> None:
    hjson_text = """
    {
      name: aes
      covergroups: [
        {
          name: status_cg
          desc: '''Coverage of the cipher_core status register.'''
        }
      ]
    }
    """
    res = _make(known=["cipher_core"]).extract(
        hjson_text, source="aes_testplan.hjson"
    )
    mentions = [t for t in res.triples
                if t.predicate == "mentions"
                and t.subject == "aes_testplan.status_cg"
                and t.object == "cipher_core"]
    assert mentions, (
        f"covergroup desc mention should fire, got triples: {res.triples}"
    )


def test_desc_mentions_layer_and_extractor_source() -> None:
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: smoke
          desc: '''Exercises the cipher_core FSM.'''
          stage: V1
          tests: ["aes_smoke"]
        }
      ]
    }
    """
    res = _make(known=["cipher_core"]).extract(
        hjson_text, source="aes_testplan.hjson"
    )
    mentions = [t for t in res.triples
                if t.predicate == "mentions" and t.object == "cipher_core"]
    assert mentions
    m = mentions[0]
    assert m.extractor_source == TESTPLAN_SOURCE
    assert m.layer == TESTPLAN_SOURCE


# -- Goal #2: SVA name normalization ----------------------------------------


def test_sva_normalize_strips_a_prefix() -> None:
    from kgweave.knowledge_graph.extraction.testplan_extractor import (
        _normalize_sva_candidate,
    )
    a = _normalize_sva_candidate("A_data_known")
    b = _normalize_sva_candidate("data_known_a")
    c = _normalize_sva_candidate("data_known")
    assert a == b == c, (
        f"normalized forms differ: A_data_known={a!r}, "
        f"data_known_a={b!r}, data_known={c!r}"
    )


def test_covers_via_normalized_match() -> None:
    # Testplan test name 'data_known_assert' should fuse to known SVA
    # 'A_data_known_a' via normalized match.
    known = ["A_data_known_a"]
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: tp_known
          desc: '''Verify SVA on data_known.'''
          stage: V2S
          tests: ["data_known_assert"]
        }
      ]
    }
    """
    res = _make(known=known).extract(hjson_text, source="aes_testplan.hjson")
    covers = [t for t in res.triples if t.predicate == "covers"]
    assert covers, f"expected covers via normalized match, got: {res.triples}"
    assert covers[0].object == "A_data_known_a"


def test_covers_skips_ambiguous_match() -> None:
    # Two SVAs both normalize to the same key but differ in canonical name.
    # Conservative path should skip rather than emit a wrong edge.
    known = ["A_count_a", "count_a"]  # both normalize to "count"
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: tp_count
          desc: '''Verify counter SVA.'''
          stage: V2S
          tests: ["count_check"]
        }
      ]
    }
    """
    res = _make(known=known).extract(hjson_text, source="aes_testplan.hjson")
    covers = [t for t in res.triples if t.predicate == "covers"]
    # Conservative: when ambiguous (only containment matches and >1 hit),
    # don't emit a covers edge.
    assert not covers, (
        f"ambiguous normalized match should be skipped, got covers: {covers}"
    )


# -- Goal #3: structural (regex-free) code-span stripping -------------------


def test_no_compiled_regex_patterns_in_module() -> None:
    """_FENCED_BLOCK_RE and _INLINE_CODE_RE must be removed; module uses
    structural parsing, not compiled regex, for code-span suppression.

    This test would have failed before iter-014 because the module-level
    ``_FENCED_BLOCK_RE`` and ``_INLINE_CODE_RE`` compiled patterns existed.
    """
    import kgweave.knowledge_graph.extraction.testplan_extractor as _mod

    assert not hasattr(_mod, "_FENCED_BLOCK_RE"), (
        "_FENCED_BLOCK_RE compiled regex must be removed; use structural scanner"
    )
    assert not hasattr(_mod, "_INLINE_CODE_RE"), (
        "_INLINE_CODE_RE compiled regex must be removed; use structural scanner"
    )


def test_fenced_block_suppresses_entity_mention() -> None:
    """Entity name inside a fenced code block must NOT produce a mentions edge.

    Verifies that the structural fenced-block scanner (introduced in iter-014)
    correctly blanks the entity name even when the block contains a literal
    newline (``\\n``), matching the re.DOTALL behaviour of the old regex.
    """
    import json as _json

    desc = "Before. ```\ncipher_core\n``` after."
    hjson_text = _json.dumps({
        "testpoints": [{
            "name": "smoke",
            "desc": desc,
            "stage": "V1",
            "tests": ["aes_smoke"],
        }]
    })
    res = _make(known=["cipher_core"]).extract(hjson_text, source="test.hjson")
    mentions = [t for t in res.triples if t.predicate == "mentions"]
    assert not any(t.object == "cipher_core" for t in mentions), (
        f"entity inside fenced block must not produce mentions edge, got: {mentions}"
    )


def test_strip_code_spans_preserves_length() -> None:
    """_strip_code_spans must return a string of the same byte-length as the
    input (positions used by _evidence_window must remain valid).

    The structural scanner introduced in iter-014 must maintain this invariant.
    """
    from kgweave.knowledge_graph.extraction.testplan_extractor import (
        TestplanExtractor,
    )

    cases = [
        "plain text",
        "has `inline` code",
        "fenced ```\nblock\n``` here",
        "multiple `a` and `b` spans",
        "",
    ]
    extractor = TestplanExtractor()
    for text in cases:
        result = extractor._strip_code_spans(text)
        assert len(result) == len(text), (
            f"_strip_code_spans changed length for {text!r}: "
            f"{len(text)} -> {len(result)}"
        )


def test_normalize_sva_candidate_consecutive_special_chars() -> None:
    """_normalize_sva_candidate must collapse multiple consecutive non-alnum
    chars to a single underscore separator (structural char scanner).

    Input ``A__data___known_a`` normalises identically to ``data_known``.
    This was previously handled by ``re.sub(r'[^a-z0-9]+', '_', s)``; the
    structural replacement must preserve this behaviour.
    """
    from kgweave.knowledge_graph.extraction.testplan_extractor import (
        _normalize_sva_candidate,
    )

    # Multi-underscore separators collapse to single separator after
    # prefix/suffix stripping (same as old re.sub behaviour).
    result = _normalize_sva_candidate("A__data___known_a")
    assert result == "data_known", (
        f"expected 'data_known', got {result!r}"
    )
