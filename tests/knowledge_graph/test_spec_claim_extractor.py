# @summary
# TDD coverage for SpecClaimExtractor — verifies claim-type emission, target
# fusion, verification_strength propagation, decomposes_into edges, layer tag,
# evidence preservation, malformed-LLM resilience, and a gated real-LLM smoke.
# All unit tests use FakeLLMProvider; no network or API key required.
# @end-summary
"""Tests for the LLM spec-claim extractor."""

from __future__ import annotations

import json
import os

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Entity
from kgweave.knowledge_graph.extraction import (
    FakeLLMProvider,
    LLM_DOC_SOURCE,
    SpecClaimExtractor,
)


_BASIC_MD = (
    "# AES Theory of Operation\n\n"
    "The aes_cipher_core completes a single block in 14 cycles.\n"
)


def _payload(*claims):
    return json.dumps({"claims": list(claims)})


def test_behavioral_claim_extracted() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "BehavioralClaim",
            "target": "aes_cipher_core",
            "evidence_span": "The aes_cipher_core completes a single block in 14 cycles.",
            "verification_strength": "coverage",
            "fields": {"behavior": "completion_latency", "value": "14 cycles"},
        })
    ])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract(_BASIC_MD, source="aes/doc/theory.md")
    types = {e.type for e in res.entities}
    assert "BehavioralClaim" in types


def test_structural_claim_extracted() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "StructuralClaim",
            "target": "aes",
            "evidence_span": "AES has a 128-bit data path.",
            "verification_strength": "equivalence",
            "fields": {"attribute": "data_path_width", "value": "128 bits"},
        })
    ])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract("# Top\n\nAES has a 128-bit data path.\n", source="x.md")
    assert any(e.type == "StructuralClaim" for e in res.entities)


def test_security_claim_extracted() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "SecurityClaim",
            "target": "aes_cipher_core",
            "evidence_span": "The AES core is constant-time.",
            "verification_strength": "unverified",
            "fields": {"property": "constant_time", "threat_model": "timing_side_channel"},
        })
    ])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract(
        "# Security\n\nThe AES core is constant-time.\n",
        source="security.md",
    )
    assert any(e.type == "SecurityClaim" for e in res.entities)


def test_target_fusion_to_known_entity() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "BehavioralClaim",
            "target": "AES_CIPHER_CORE",  # case differs from canonical
            "evidence_span": "The cipher completes in 14 cycles.",
            "verification_strength": "coverage",
            "fields": {},
        })
    ])
    ext = SpecClaimExtractor(
        llm_provider=provider,
        known_entity_names=["aes_cipher_core"],
    )
    res = ext.extract(_BASIC_MD, source="aes.md")
    target_edges = [t for t in res.triples if t.predicate == "target_entity"]
    assert len(target_edges) == 1
    assert target_edges[0].object == "aes_cipher_core"


def test_target_unknown_kept_as_string() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "ProtocolClaim",
            "target": "mystery_block",
            "evidence_span": "The mystery_block samples on the rising edge.",
            "verification_strength": "unverified",
            "fields": {},
        })
    ])
    ext = SpecClaimExtractor(
        llm_provider=provider, known_entity_names=["aes_cipher_core"]
    )
    res = ext.extract("# Top\n\nbody.\n", source="x.md")
    target_edges = [t for t in res.triples if t.predicate == "target_entity"]
    assert len(target_edges) == 1
    # No fusion — the literal target name is the object.
    assert target_edges[0].object == "mystery_block"


def test_verification_strength_field_propagates() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "BehavioralClaim",
            "target": "aes",
            "evidence_span": "Latency is 14 cycles.",
            "verification_strength": "coverage",
            "fields": {},
        })
    ])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract(_BASIC_MD, source="x.md")
    claim_entities = [e for e in res.entities if e.type == "BehavioralClaim"]
    assert claim_entities
    aliases = claim_entities[0].aliases
    assert any(a == "verification_strength=coverage" for a in aliases)


def test_decomposes_into_edge_emitted() -> None:
    provider = FakeLLMProvider([
        _payload(
            {
                "id": "p1",
                "type": "BehavioralClaim",
                "target": "aes",
                "evidence_span": "AES handles encrypt and decrypt.",
                "verification_strength": "decomposed",
                "fields": {},
            },
            {
                "id": "c1",
                "type": "BehavioralClaim",
                "target": "aes",
                "evidence_span": "Encrypt completes in 14 cycles.",
                "verification_strength": "coverage",
                "parent_id": "p1",
                "fields": {},
            },
        )
    ])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract("# AES\n\nbody.\n", source="x.md")
    decomp = [t for t in res.triples if t.predicate == "decomposes_into"]
    assert len(decomp) == 1


def test_layer_tag_set_to_llm_doc() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "BehavioralClaim",
            "target": "aes",
            "evidence_span": "Latency is 14 cycles.",
            "verification_strength": "coverage",
            "fields": {},
        })
    ])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract(_BASIC_MD, source="x.md")
    for e in res.entities:
        assert e.layer == LLM_DOC_SOURCE
    for t in res.triples:
        assert t.layer == LLM_DOC_SOURCE
        assert t.extractor_source == LLM_DOC_SOURCE


def test_evidence_span_preserved() -> None:
    sentence = "The cipher completes in 14 cycles."
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "BehavioralClaim",
            "target": "aes",
            "evidence_span": sentence,
            "verification_strength": "coverage",
            "fields": {},
        })
    ])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract(_BASIC_MD, source="x.md")
    edges = [t for t in res.triples if t.predicate == "claims_about"]
    assert edges and edges[0].evidence_span == sentence


def test_round_trip_extract_to_backend() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "BehavioralClaim",
            "target": "aes_cipher_core",
            "evidence_span": "Cipher completes in 14 cycles.",
            "verification_strength": "coverage",
            "fields": {},
        })
    ])
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="aes_cipher_core", type="RTL_Module"),
    ])
    ext = SpecClaimExtractor(
        llm_provider=provider,
        known_entity_names=["aes_cipher_core"],
    )
    res = ext.extract(_BASIC_MD, source="x.md")
    backend.upsert_entities(res.entities)
    backend.upsert_triples(res.triples)

    # Section, claim, and target node all present; edges round-trip.
    layer_ents = backend.entities_by_layer(LLM_DOC_SOURCE)
    assert any(e.type == "BehavioralClaim" for e in layer_ents)
    layer_trips = backend.triples_by_layer(LLM_DOC_SOURCE)
    preds = {t.predicate for t in layer_trips}
    assert "claims_about" in preds
    assert "target_entity" in preds


def test_malformed_llm_response_handled() -> None:
    provider = FakeLLMProvider(["this is not json {{{"])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract(_BASIC_MD, source="x.md")
    assert res.entities == []
    assert res.triples == []


def test_unknown_claim_type_dropped() -> None:
    provider = FakeLLMProvider([
        _payload({
            "id": "c1",
            "type": "FantasyClaim",
            "target": "aes",
            "evidence_span": "Anything.",
            "verification_strength": "coverage",
            "fields": {},
        })
    ])
    ext = SpecClaimExtractor(llm_provider=provider)
    res = ext.extract(_BASIC_MD, source="x.md")
    assert all(e.type != "FantasyClaim" for e in res.entities)


def test_claim_extraction_prompt_no_ot_module_names() -> None:
    """CLAIM_EXTRACTION_PROMPT must not reference any aes_-prefixed module names.

    The prompt uses an example JSON block to illustrate the output schema.
    That example must use a generic module name, not an OpenTitan-specific
    identifier like ``aes_cipher_core``.
    """
    import re
    from kgweave.knowledge_graph.extraction.spec_claim_extractor import (
        CLAIM_EXTRACTION_PROMPT,
    )

    ot_pattern = re.compile(r"\baes_[a-z][a-z0-9_]*")
    matches = ot_pattern.findall(CLAIM_EXTRACTION_PROMPT)
    assert matches == [], (
        f"CLAIM_EXTRACTION_PROMPT contains OT-specific module identifiers: {matches}. "
        "Use a generic placeholder (e.g. 'example_module') instead."
    )


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="real-LLM smoke test gated on OPENAI_API_KEY",
)
def test_real_llm_smoke() -> None:  # pragma: no cover - external resource
    """Smoke: run against a real OpenAI-compatible provider when env is set."""
    from kgweave.knowledge_graph.common.protocols import get_default_llm

    class _Adapter:
        def __init__(self) -> None:
            self.client = get_default_llm()

        def generate(self, prompt: str) -> str:
            resp = self.client.json_completion(
                [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ]
            )
            return resp.content

    sample = (
        "# AES Theory of Operation\n\n"
        "The cipher core completes a single 128-bit block in 14 cycles.\n"
        "The implementation is constant-time.\n"
    )
    ext = SpecClaimExtractor(
        llm_provider=_Adapter(),
        known_entity_names=["aes_cipher_core"],
    )
    res = ext.extract(sample, source="aes.md")
    assert len(res.entities) >= 1
