# @summary
# TDD coverage for TestplanNormalizer — exercises canonical-shape coercion,
# round-trip through TestplanExtractor, empty-input handling, and malformed-
# LLM resilience. All tests use FakeLLMProvider; no network required.
# @end-summary
"""Tests for the freeform-to-canonical testplan normalizer."""

from __future__ import annotations

import json

from kgweave.knowledge_graph.extraction import (
    FakeLLMProvider,
    TestplanExtractor,
    TestplanNormalizer,
)


_FREEFORM_MD = (
    "# AES Testplan\n\n"
    "## Testpoints\n\n"
    "### smoke_encrypt\n"
    "Run a basic encrypt operation and check the output.\n"
    "Tests: aes_smoke_test.\n"
    "Stage: V1.\n"
)


def _canon_payload():
    return json.dumps({
        "name": "aes_testplan",
        "testpoints": [
            {
                "name": "smoke_encrypt",
                "desc": "Run a basic encrypt operation and check the output.",
                "stage": "V1",
                "tests": ["aes_smoke_test"],
                "tags": ["smoke"],
            }
        ],
        "covergroups": [
            {"name": "aes_cg", "desc": "Cover the AES modes."}
        ],
    })


def test_markdown_with_testpoint_section() -> None:
    norm = TestplanNormalizer(llm_provider=FakeLLMProvider([_canon_payload()]))
    out = norm.normalize(_FREEFORM_MD, source="aes_testplan.md")
    assert any(tp["name"] == "smoke_encrypt" for tp in out["testpoints"])


def test_canonical_output_shape() -> None:
    norm = TestplanNormalizer(llm_provider=FakeLLMProvider([_canon_payload()]))
    out = norm.normalize(_FREEFORM_MD, source="aes_testplan.md")
    assert "name" in out
    assert isinstance(out["testpoints"], list)
    assert isinstance(out["covergroups"], list)


def test_testpoint_field_structure() -> None:
    norm = TestplanNormalizer(llm_provider=FakeLLMProvider([_canon_payload()]))
    out = norm.normalize(_FREEFORM_MD, source="aes_testplan.md")
    tp = out["testpoints"][0]
    for key in ("name", "desc", "stage", "tests", "tags"):
        assert key in tp
    assert isinstance(tp["tests"], list)
    assert isinstance(tp["tags"], list)


def test_round_trip_through_testplan_extractor() -> None:
    norm = TestplanNormalizer(llm_provider=FakeLLMProvider([_canon_payload()]))
    canonical = norm.normalize(_FREEFORM_MD, source="aes_testplan.md")
    hjson_text = json.dumps(canonical)

    extractor = TestplanExtractor()
    res = extractor.extract(hjson_text, source="aes_testplan.hjson")
    types = {e.type for e in res.entities}
    assert "Testpoint" in types
    # Stage entity is created when the testpoint declares one.
    assert "Stage" in types or any(t.predicate == "has_stage" for t in res.triples)


def test_handles_empty_input() -> None:
    norm = TestplanNormalizer(llm_provider=FakeLLMProvider([]))
    out = norm.normalize("", source="empty.md")
    assert out["testpoints"] == []
    assert out["covergroups"] == []
    assert out["name"]


def test_malformed_llm_response_handled() -> None:
    norm = TestplanNormalizer(
        llm_provider=FakeLLMProvider(["not json at all <<<"])
    )
    out = norm.normalize(_FREEFORM_MD, source="bad.md")
    # Returns the empty canonical shape; no crash.
    assert out["testpoints"] == []
    assert out["covergroups"] == []


def test_normalizer_prompt_no_opentitan_reference() -> None:
    """TESTPLAN_NORMALIZER_PROMPT must not mention OpenTitan or lowrisc.

    The prompt format describes a generic testplan HJSON schema — the
    'OpenTitan-style' qualifier is project-specific and must be removed.
    """
    from kgweave.knowledge_graph.extraction.testplan_normalizer import (
        TESTPLAN_NORMALIZER_PROMPT,
    )

    prompt_lower = TESTPLAN_NORMALIZER_PROMPT.lower()
    for forbidden in ("opentitan", "lowrisc"):
        assert forbidden not in prompt_lower, (
            f"TESTPLAN_NORMALIZER_PROMPT contains project-specific term '{forbidden}'. "
            "Use generic language (e.g. 'testplan-style HJSON-compatible') instead."
        )


def test_drops_invalid_testpoint_entries() -> None:
    bad = json.dumps({
        "name": "x",
        "testpoints": [
            {"name": "ok_tp", "desc": "good"},
            {"desc": "no name — drop"},
            "not a dict",
        ],
        "covergroups": [{"desc": "no name — drop"}, {"name": "cg_ok"}],
    })
    norm = TestplanNormalizer(llm_provider=FakeLLMProvider([bad]))
    out = norm.normalize("# tp", source="x.md")
    assert [tp["name"] for tp in out["testpoints"]] == ["ok_tp"]
    assert [cg["name"] for cg in out["covergroups"]] == ["cg_ok"]
