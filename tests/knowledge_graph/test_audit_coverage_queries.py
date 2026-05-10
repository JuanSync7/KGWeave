"""Tests for audit/coverage query helpers (Stage 3).

These tests exercise the audit-vs-test-completeness split via two free
functions over a populated NetworkX-backed knowledge graph.
"""

from __future__ import annotations

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple
from kgweave.knowledge_graph.queries import (
    audit_orphan_tests,
    confidence_tier_rank,
    coverage_gaps_by_target,
)


def _mk_test(name: str, is_test):
    return Entity(name=name, type="SW_Test", is_test=is_test)


def _mk_module(name: str):
    return Entity(name=name, type="RTL_Module")


def _mk_edge(subj: str, obj: str, *, tier: str = "high", resolved: bool = True):
    return Triple(
        subject=subj,
        predicate="tests_module",
        object=obj,
        confidence_tier=tier,
        resolved=resolved,
    )


# ---------------------------------------------------------------------------
# audit_orphan_tests
# ---------------------------------------------------------------------------


def test_audit_orphan_includes_real_test_with_no_resolved_edge():
    be = NetworkXBackend()
    be.upsert_entities([_mk_test("test_alpha", True)])
    # only an unresolved edge — does not save it from being orphan
    be.upsert_triples([_mk_edge("test_alpha", "<unknown>", tier="low", resolved=False)])
    assert audit_orphan_tests(be) == ["test_alpha"]


def test_audit_orphan_excludes_test_with_resolved_edge():
    be = NetworkXBackend()
    be.upsert_entities([_mk_test("test_beta", True), _mk_module("mod_b")])
    be.upsert_triples([_mk_edge("test_beta", "mod_b", tier="high", resolved=True)])
    assert audit_orphan_tests(be) == []


def test_audit_orphan_excludes_is_test_false_entity():
    # crt0 case: not a real test, must be excluded from audit
    be = NetworkXBackend()
    be.upsert_entities([_mk_test("crt0", False)])
    assert audit_orphan_tests(be) == []


def test_audit_orphan_excludes_is_test_none_entity():
    be = NetworkXBackend()
    be.upsert_entities([_mk_test("unreadable", None)])
    assert audit_orphan_tests(be) == []


def test_audit_orphan_test_with_both_resolved_and_unresolved_edges_not_orphan():
    be = NetworkXBackend()
    be.upsert_entities([_mk_test("test_mixed", True), _mk_module("mod_m")])
    be.upsert_triples(
        [
            _mk_edge("test_mixed", "mod_m", tier="medium", resolved=True),
            _mk_edge("test_mixed", "<unknown>", tier="low", resolved=False),
        ]
    )
    assert audit_orphan_tests(be) == []


def test_audit_orphan_returns_alphabetical():
    be = NetworkXBackend()
    be.upsert_entities(
        [
            _mk_test("test_zulu", True),
            _mk_test("test_alpha", True),
            _mk_test("test_mike", True),
        ]
    )
    assert audit_orphan_tests(be) == ["test_alpha", "test_mike", "test_zulu"]


# ---------------------------------------------------------------------------
# coverage_gaps_by_target
# ---------------------------------------------------------------------------


def test_coverage_gap_module_with_zero_inbound_listed():
    be = NetworkXBackend()
    be.upsert_entities([_mk_module("mod_lonely")])
    assert coverage_gaps_by_target(be) == ["mod_lonely"]


def test_coverage_gap_module_with_low_tier_inbound_excluded_when_floor_medium():
    be = NetworkXBackend()
    be.upsert_entities([_mk_test("t1", True), _mk_module("mod_low")])
    be.upsert_triples([_mk_edge("t1", "mod_low", tier="low", resolved=True)])
    # floor=low: covered (excluded from gap list)
    assert coverage_gaps_by_target(be, min_confidence="low") == []
    # floor=medium: low does not satisfy floor, becomes a gap
    assert coverage_gaps_by_target(be, min_confidence="medium") == ["mod_low"]
    assert coverage_gaps_by_target(be, min_confidence="high") == ["mod_low"]


def test_coverage_gap_module_with_high_tier_inbound_excluded():
    be = NetworkXBackend()
    be.upsert_entities([_mk_test("t1", True), _mk_module("mod_high")])
    be.upsert_triples([_mk_edge("t1", "mod_high", tier="high", resolved=True)])
    assert coverage_gaps_by_target(be, min_confidence="high") == []


def test_coverage_gap_unresolved_edge_does_not_count_as_coverage():
    be = NetworkXBackend()
    be.upsert_entities([_mk_test("t1", True), _mk_module("mod_unres")])
    # An unresolved high-tier edge must not save the module from being a gap.
    be.upsert_triples(
        [_mk_edge("t1", "mod_unres", tier="high", resolved=False)]
    )
    assert coverage_gaps_by_target(be, min_confidence="low") == ["mod_unres"]


def test_coverage_gap_filters_by_node_type():
    be = NetworkXBackend()
    be.upsert_entities(
        [
            _mk_module("mod_a"),
            Entity(name="something_else", type="DV_Test"),
        ]
    )
    out = coverage_gaps_by_target(be, node_type="RTL_Module")
    assert out == ["mod_a"]


def test_coverage_gap_returns_alphabetical():
    be = NetworkXBackend()
    be.upsert_entities([_mk_module("mod_z"), _mk_module("mod_a"), _mk_module("mod_m")])
    assert coverage_gaps_by_target(be) == ["mod_a", "mod_m", "mod_z"]


# ---------------------------------------------------------------------------
# confidence_tier_rank
# ---------------------------------------------------------------------------


def test_confidence_tier_rank_ordering():
    assert confidence_tier_rank("low") == 0
    assert confidence_tier_rank("medium") == 1
    assert confidence_tier_rank("high") == 2
    assert confidence_tier_rank("garbage") == -1
    assert confidence_tier_rank("") == -1
    assert confidence_tier_rank("low") < confidence_tier_rank("medium")
    assert confidence_tier_rank("medium") < confidence_tier_rank("high")
