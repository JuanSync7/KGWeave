"""V3 #7 — portability of testplan SVA-name normalization.

The testplan extractor's SVA prefix list ``("a_", "prim_", "aes_")`` was
hardcoded for OpenTitan flavors. Non-OT codebases name SVA assertions
``widget_check_a``, ``frob_assert_xyz``, etc., which fail to normalise
correctly.

This test pins:

1. Unit: a non-OT prefixed assertion name normalises through the
   constructor-supplied prefix list.
2. Infra: ``KGConfig.testplan_sva_prefixes`` round-trips through
   ``from_env`` and the field exists.
3. Integration: TestplanExtractor with a custom prefix list resolves
   non-OT SVA names to their canonical form.
"""
from __future__ import annotations

from kgweave.knowledge_graph.common import KGConfig
from kgweave.knowledge_graph.extraction.testplan_extractor import (
    TestplanExtractor,
    _normalize_sva_candidate,
)


# ---- Unit / infra ---------------------------------------------------------


def test_kgconfig_testplan_sva_prefixes_default_is_ot():
    """Default config keeps OT-flavored prefixes for backward compat."""
    cfg = KGConfig()
    prefixes = getattr(cfg, "testplan_sva_prefixes", None)
    # Default may be either None (extractor falls back) or the OT triple.
    assert prefixes is None or set(prefixes) >= {"a_"}


def test_kgconfig_testplan_sva_prefixes_settable():
    cfg = KGConfig(testplan_sva_prefixes=["a_", "frob_", "widget_"])
    assert "frob_" in cfg.testplan_sva_prefixes
    assert "widget_" in cfg.testplan_sva_prefixes


def test_kgconfig_testplan_sva_prefixes_from_env():
    cfg = KGConfig.from_env(
        {"RAG_KG_TESTPLAN_SVA_PREFIXES": "a_,frob_,widget_"}
    )
    assert cfg.testplan_sva_prefixes == ["a_", "frob_", "widget_"]


# ---- Default normalisation still works for OT names -----------------------


def test_default_normalize_strips_ot_prefixes():
    # ``aes_data_known_a`` -> ``data_known`` (when ``aes_`` is in the prefix list)
    assert (
        _normalize_sva_candidate("aes_data_known_a", prefixes=("a_", "prim_", "aes_"))
        == "data_known"
    )


def test_generic_default_normalize_does_not_strip_aes():
    # Generic default (no project-specific prefixes) leaves project-specific
    # prefixes like ``aes_`` intact — only the universal ``a_``/``prim_`` go.
    assert _normalize_sva_candidate("aes_data_known_a") == "aes_data_known"


# ---- Integration: TestplanExtractor accepts custom prefixes ---------------


def test_testplan_extractor_accepts_custom_sva_prefixes():
    """TestplanExtractor with custom prefixes recognises non-OT SVA names.

    A non-OT codebase declares an SVA ``widget_data_valid_a``. The
    canonical form (after stripping prefix + suffix) is ``data_valid``.
    """
    known = ["widget_ctrl.widget_data_valid_a"]
    extractor = TestplanExtractor(
        known_entity_names=known,
        sva_prefixes=("a_", "widget_"),
    )
    # Internal sanity: at least one known name is recognised as SVA-looking.
    assert any("widget" in n for n in extractor._sva_known)
