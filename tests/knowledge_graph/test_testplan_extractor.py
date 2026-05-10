# @summary
# Tests for TestplanExtractor — testpoint/covergroup/stage/DVTest emission,
# fusion to known SVA names, lazy stage de-duplication, and round-trip
# through the NetworkXBackend.
# @end-summary
"""TDD coverage for the OpenTitan-style HJSON testplan extractor."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.extraction.testplan_extractor import (
    TestplanExtractor,
    TESTPLAN_SOURCE,
)


_MIN_HJSON = """
{
  name: aes
  testpoints: [
    {
      name: smoke
      desc: '''Encrypt a plain text and compare.'''
      stage: V1
      tests: ["aes_smoke"]
    }
  ]
}
"""


_MULTI_HJSON = """
{
  name: aes
  testpoints: [
    {
      name: alpha
      desc: '''A.'''
      stage: V1
      tests: ["foo", "bar"]
    }
    {
      name: beta
      desc: '''B.'''
      stage: V1
      tests: ["baz"]
    }
    {
      name: gamma
      desc: '''C.'''
      stage: V2
      tests: []
    }
  ]
  covergroups: [
    {
      name: status_cg
      desc: '''Status coverage.'''
    }
  ]
}
"""


def _make(known=None) -> TestplanExtractor:
    return TestplanExtractor(known_entity_names=known or [])


def test_testpoint_entity_emitted() -> None:
    res = _make().extract(_MIN_HJSON, source="aes_testplan.hjson")
    tps = [e for e in res.entities if e.type == "Testpoint"]
    names = {e.name for e in tps}
    assert "aes_testplan.smoke" in names
    tp = next(e for e in tps if e.name == "aes_testplan.smoke")
    assert tp.extractor_source == [TESTPLAN_SOURCE]
    assert tp.sources == ["aes_testplan.hjson"]


def test_testpoint_desc_in_evidence_span() -> None:
    res = _make().extract(_MIN_HJSON, source="aes_testplan.hjson")
    tp = next(e for e in res.entities
              if e.type == "Testpoint" and e.name == "aes_testplan.smoke")
    assert any("Encrypt a plain text" in m.text for m in tp.raw_mentions)
    has_stage = [t for t in res.triples if t.predicate == "has_stage"]
    assert has_stage and "Encrypt a plain text" in has_stage[0].evidence_span


def test_tests_edges_emitted() -> None:
    res = _make().extract(_MULTI_HJSON, source="aes_testplan.hjson")
    tests_edges = [t for t in res.triples
                   if t.predicate == "tests"
                   and t.subject == "aes_testplan.alpha"]
    objs = sorted(t.object for t in tests_edges)
    assert objs == ["bar", "foo"]


def test_stage_entity_lazy_creation() -> None:
    res = _make().extract(_MULTI_HJSON, source="aes_testplan.hjson")
    stages = [e for e in res.entities if e.type == "Stage"]
    names = sorted(e.name for e in stages)
    # V1 (alpha + beta) and V2 (gamma) — each emitted once.
    assert names == ["V1", "V2"]


def test_covergroup_entity_emitted() -> None:
    res = _make().extract(_MULTI_HJSON, source="aes_testplan.hjson")
    cgs = [e for e in res.entities if e.type == "Covergroup"]
    assert any(e.name == "aes_testplan.status_cg" for e in cgs)


def test_fusion_to_known_sva() -> None:
    # If known_entity_names already contains an assertion named like the
    # test reference, emit a `covers` edge — not a fresh DVTest.
    known = ["aes.prim_count_assert"]
    hjson_text = """
    {
      name: aes
      testpoints: [
        {
          name: tp_count
          desc: '''Verify counter SVA.'''
          stage: V2S
          tests: ["prim_count_assert"]
        }
      ]
    }
    """
    res = _make(known=known).extract(hjson_text, source="aes_testplan.hjson")
    covers = [t for t in res.triples if t.predicate == "covers"]
    assert covers and covers[0].object == "aes.prim_count_assert"
    # No DVTest should have been emitted for that SVA-fused name.
    dvtests = [e for e in res.entities if e.type == "DVTest"]
    assert all(e.name != "prim_count_assert" for e in dvtests)


def test_unresolved_test_creates_dvtest() -> None:
    res = _make().extract(_MIN_HJSON, source="aes_testplan.hjson")
    dvtests = {e.name for e in res.entities if e.type == "DVTest"}
    assert "aes_smoke" in dvtests
    tests_edges = [t for t in res.triples if t.predicate == "tests"]
    assert tests_edges and tests_edges[0].object == "aes_smoke"


def test_round_trip_extract_to_backend() -> None:
    backend = NetworkXBackend()
    res = _make().extract(_MULTI_HJSON, source="aes_testplan.hjson")
    backend.upsert_entities(res.entities)
    backend.upsert_triples(res.triples)
    names = set(backend.get_all_node_names_and_aliases().keys())
    assert "aes_testplan.alpha" in names
    assert "aes_testplan.status_cg" in names
    assert "v1" in names or "V1" in names
    # Outbound edges from alpha include tests + has_stage.
    tps = backend.get_all_entities()
    assert any(e.type == "Testpoint" and e.name == "aes_testplan.beta"
               for e in tps)


def test_real_aes_testplan_smoke() -> None:
    real = (Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip"
            / "aes" / "data" / "aes_testplan.hjson")
    if not real.exists():
        pytest.skip(f"OpenTitan AES testplan not present at {real}")
    text = real.read_text()
    res = _make().extract(text, source=str(real))
    tps = [e for e in res.entities if e.type == "Testpoint"]
    assert len(tps) >= 10, f"expected >=10 testpoints, got {len(tps)}"
    cgs = [e for e in res.entities if e.type == "Covergroup"]
    assert len(cgs) >= 1
