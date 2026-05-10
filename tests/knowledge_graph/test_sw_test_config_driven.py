"""Tier A: config-driven SW→RTL resolver tests.

Asserts the resolver becomes a generic, config-driven engine while
preserving exact OpenTitan defaults when no config is supplied.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor
from kgweave.knowledge_graph.common.sw_test_config import (
    SwTestPattern,
    SwTestResolutionConfig,
    load_sw_test_config,
)


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


def _tm(result, subject=None):
    out = []
    for t in result.triples:
        if t.predicate != "tests_module":
            continue
        if subject is not None and t.subject != subject:
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# (1) Default config equals OpenTitan baked-in behavior
# ---------------------------------------------------------------------------


def test_defaults_replicate_opentitan_three_signals(tmp_path):
    """All three OpenTitan signals (include / dif call / base addr) resolve."""
    src = (
        '#include "dif_aes.h"\n'
        "int main(void){\n"
        "  uintptr_t b = TOP_EARLGREY_AES_BASE_ADDR;\n"
        "  dif_aes_init(&h);\n"
        "  return (int)b;\n"
        "}\n"
    )
    _write(tmp_path, "z.c", src)

    # Default-arg path: no config supplied
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="z")
    aes_edges = [e for e in edges if e.object == "aes" and e.resolved]
    assert len(aes_edges) == 1
    assert aes_edges[0].confidence_tier == "high"


def test_defaults_match_explicit_load_sw_test_config_none(tmp_path):
    """Passing load_sw_test_config(None) explicitly produces identical edges."""
    src = (
        '#include "dif_aes.h"\n'
        "int main(void){ dif_aes_init(&h); return 0; }\n"
    )
    _write(tmp_path, "z.c", src)

    ex_default = SWTestExtractor(known_entity_names=["aes"])
    res_default = ex_default.extract(source=str(tmp_path))

    cfg = load_sw_test_config(None)
    ex_cfg = SWTestExtractor(known_entity_names=["aes"], sw_test_config=cfg)
    res_cfg = ex_cfg.extract(source=str(tmp_path))

    def _key(t):
        return (t.subject, t.predicate, t.object, t.confidence_tier, t.resolved)

    assert sorted(map(_key, res_default.triples)) == sorted(map(_key, res_cfg.triples))


# ---------------------------------------------------------------------------
# (2) CamelCase project: aesBaseAddress + camel transform via lowercase
# ---------------------------------------------------------------------------


def test_camelcase_base_address_pattern(tmp_path):
    src = "int main(void){ volatile uintptr_t b = aesBaseAddress; (void)b; return 0; }\n"
    _write(tmp_path, "demo.c", src)

    cfg = SwTestResolutionConfig(
        patterns=[
            SwTestPattern(
                name="camel_base_address",
                regex=r"\b(?P<module>[a-z][a-zA-Z0-9]*)BaseAddress\b",
                confidence_tier="high",
                transform="lowercase",
            ),
        ],
        test_markers=[r"int\s+main\s*\("],
    )

    ex = SWTestExtractor(known_entity_names=["aes"], sw_test_config=cfg)
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="demo")
    resolved = [e for e in edges if e.resolved]
    assert len(resolved) == 1
    assert resolved[0].object == "aes"
    assert resolved[0].confidence_tier == "high"


# ---------------------------------------------------------------------------
# (3) No-underscore vendor macro
# ---------------------------------------------------------------------------


def test_no_underscore_vendor_macro(tmp_path):
    src = "int main(void){ volatile uintptr_t b = AES_BASE_ADDRESS; (void)b; return 0; }\n"
    _write(tmp_path, "v.c", src)

    cfg = SwTestResolutionConfig(
        patterns=[
            SwTestPattern(
                name="vendor_base_addr",
                regex=r"\b(?P<module>[A-Z][A-Z0-9]*)_BASE_ADDRESS\b",
                confidence_tier="high",
                transform="lowercase",
            ),
        ],
        test_markers=[r"int\s+main\s*\("],
    )
    ex = SWTestExtractor(known_entity_names=["aes"], sw_test_config=cfg)
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="v")
    resolved = [e for e in edges if e.resolved]
    assert len(resolved) == 1
    assert resolved[0].object == "aes"


# ---------------------------------------------------------------------------
# (4) Pattern ordering / dedup — first matching pattern wins
# ---------------------------------------------------------------------------


def test_pattern_ordering_dedup_single_edge(tmp_path):
    """When multiple patterns match the same (test, module), one edge is emitted."""
    src = (
        '#include "dif_aes.h"\n'
        "int main(void){ uintptr_t b = TOP_EARLGREY_AES_BASE_ADDR; (void)b;\n"
        "  dif_aes_init(&h); return 0; }\n"
    )
    _write(tmp_path, "m.c", src)

    # Default config — three OpenTitan patterns all match aes.
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="m")
    aes_edges = [e for e in edges if e.object == "aes"]
    assert len(aes_edges) == 1


# ---------------------------------------------------------------------------
# (5) Transform application: lowercase vs none
# ---------------------------------------------------------------------------


def test_transform_lowercase_normalises_module_name(tmp_path):
    src = "int main(void){ volatile uintptr_t b = AES_BASE_ADDRESS; (void)b; return 0; }\n"
    _write(tmp_path, "x.c", src)

    cfg = SwTestResolutionConfig(
        patterns=[
            SwTestPattern(
                name="upper_macro",
                regex=r"\b(?P<module>[A-Z][A-Z0-9]*)_BASE_ADDRESS\b",
                confidence_tier="high",
                transform="lowercase",
            ),
        ],
        test_markers=[r"int\s+main\s*\("],
    )
    ex = SWTestExtractor(known_entity_names=["aes"], sw_test_config=cfg)
    res = ex.extract(source=str(tmp_path))
    aes_edges = [e for e in _tm(res, subject="x") if e.resolved]
    assert aes_edges and aes_edges[0].object == "aes"


def test_transform_none_preserves_case(tmp_path):
    """With transform=none, a capture in a form that doesn't match the
    canonical module casing only resolves through case-insensitive fallback;
    the captured-as-typed value is not forced lowercase before lookup."""
    src = "int main(void){ foo_init(); return 0; }\n"
    _write(tmp_path, "y.c", src)

    cfg = SwTestResolutionConfig(
        patterns=[
            SwTestPattern(
                name="case_preserving",
                regex=r"\b(?P<module>foo)_init\b",
                confidence_tier="high",
                transform="none",
            ),
        ],
        test_markers=[r"int\s+main\s*\("],
    )
    ex = SWTestExtractor(known_entity_names=["foo"], sw_test_config=cfg)
    res = ex.extract(source=str(tmp_path))
    edges = [e for e in _tm(res, subject="y") if e.resolved]
    assert edges and edges[0].object == "foo"


# ---------------------------------------------------------------------------
# (6) Custom test_markers
# ---------------------------------------------------------------------------


def test_custom_test_markers(tmp_path):
    src = "void entry_point(void){ }\n"
    _write(tmp_path, "ep.c", src)

    cfg = SwTestResolutionConfig(
        patterns=[],
        test_markers=[r"\bentry_point\s*\("],
    )
    ex = SWTestExtractor(known_entity_names=["aes"], sw_test_config=cfg)
    res = ex.extract(source=str(tmp_path))
    e = next(en for en in res.entities if en.name == "ep")
    assert e.is_test is True


def test_default_markers_dont_match_custom(tmp_path):
    """A file with only entry_point doesn't trip default markers."""
    src = "void entry_point(void){ }\n"
    _write(tmp_path, "ep.c", src)

    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    e = next(en for en in res.entities if en.name == "ep")
    assert e.is_test is False


# ---------------------------------------------------------------------------
# (7) Backward compat — no-config behavior is unchanged
# ---------------------------------------------------------------------------


def test_no_config_arg_byte_identical_to_pre_refactor(tmp_path):
    """Snapshot of the OpenTitan three-signal triples with no config."""
    files = {
        "a.c": '#include "dif_aes.h"\nint main(void){ return 0; }\n',
        "b.c": "int main(void){ dif_hmac_init(&h); return 0; }\n",
        "c.c": "void _start(void){ uintptr_t b = TOP_EARLGREY_AES_BASE_ADDR; (void)b; }\n",
        "d.c": "int main(void){ return 0; }\n",  # unresolved sentinel
    }
    for name, body in files.items():
        _write(tmp_path, name, body)

    ex = SWTestExtractor(known_entity_names=["aes", "hmac"])
    res = ex.extract(source=str(tmp_path))

    # Build a snapshot of (subject, predicate, object, tier, resolved).
    triples_snap = sorted(
        (t.subject, t.predicate, t.object, t.confidence_tier, bool(t.resolved))
        for t in res.triples
        if t.predicate == "tests_module"
    )
    assert triples_snap == [
        ("a", "tests_module", "aes", "high", True),
        ("b", "tests_module", "hmac", "high", True),
        ("c", "tests_module", "aes", "high", True),
        ("d", "tests_module", "<unknown>", "low", False),
    ]


# ---------------------------------------------------------------------------
# (8) Confidence tier per pattern
# ---------------------------------------------------------------------------


def test_per_pattern_confidence_tier_propagates(tmp_path):
    src = "int main(void){ MED_aes_call(); LOW_aes_call(); return 0; }\n"
    _write(tmp_path, "t.c", src)

    cfg = SwTestResolutionConfig(
        patterns=[
            SwTestPattern(
                name="medium_pat",
                regex=r"\bMED_(?P<module>[a-z]+)_call\b",
                confidence_tier="medium",
                transform="none",
            ),
        ],
        test_markers=[r"int\s+main\s*\("],
    )
    ex = SWTestExtractor(known_entity_names=["aes"], sw_test_config=cfg)
    res = ex.extract(source=str(tmp_path))
    edges = [e for e in _tm(res, subject="t") if e.resolved]
    assert edges
    assert edges[0].confidence_tier == "medium"


# ---------------------------------------------------------------------------
# (9) YAML loader round-trip
# ---------------------------------------------------------------------------


def test_load_sw_test_config_from_yaml(tmp_path):
    yaml_text = dedent(
        """
        patterns:
          - name: my_pat
            description: "test"
            regex: '\\b(?P<module>[a-z]+)BaseAddress\\b'
            confidence_tier: high
            transform: lowercase
        test_markers:
          - 'int\\s+main\\s*\\('
        preprocessor_strip_if_zero: false
        """
    )
    yml = tmp_path / "cfg.yaml"
    yml.write_text(yaml_text)

    cfg = load_sw_test_config(str(yml))
    assert len(cfg.patterns) == 1
    p = cfg.patterns[0]
    assert p.name == "my_pat"
    assert p.confidence_tier == "high"
    assert p.transform == "lowercase"
    assert p.regex.search("aesBaseAddress") is not None
    assert cfg.preprocessor_strip_if_zero is False


# ---------------------------------------------------------------------------
# Phase 2: project_conventions integration
# ---------------------------------------------------------------------------


def test_load_sw_test_config_strict_generic_warns_and_returns_empty(caplog):
    """No YAML supplied AND project_conventions.profile != 'opentitan' →
    return an empty patterns config and emit a WARNING."""
    import logging

    from kgweave.knowledge_graph.common.types import ProjectConventions

    pc = ProjectConventions()  # profile=None, strict generic
    with caplog.at_level(
        logging.WARNING, logger="rag.knowledge_graph.sw_test_config"
    ):
        cfg = load_sw_test_config(None, project_conventions=pc)

    assert cfg.patterns == [], "expected empty patterns for strict-generic"
    assert any(
        "sw->rtl resolution will produce no links" in rec.getMessage().lower()
        for rec in caplog.records
    )


def test_load_sw_test_config_opentitan_profile_silent_fallback(caplog):
    """When project_conventions.profile == 'opentitan' AND no YAML, return
    OT defaults silently (no warning emitted by the loader)."""
    import logging

    from kgweave.knowledge_graph.common.types import ProjectConventions

    pc = ProjectConventions.opentitan()
    with caplog.at_level(
        logging.WARNING, logger="rag.knowledge_graph.sw_test_config"
    ):
        cfg = load_sw_test_config(None, project_conventions=pc)

    assert cfg.patterns, "OT profile must keep OT defaults populated"
    # No warnings about empty / fallback profile
    assert not any(
        "produce no links" in rec.getMessage().lower()
        for rec in caplog.records
    )


def test_load_sw_test_config_explicit_sw_test_patterns_override(tmp_path):
    """When project_conventions.sw_test_patterns is set explicitly, those
    patterns are used verbatim — no YAML, no OT fallback."""
    from kgweave.knowledge_graph.common.sw_test_config import SwTestPattern
    from kgweave.knowledge_graph.common.types import ProjectConventions
    from kgweave.knowledge_graph.extraction.sw_test_extractor import (
        SWTestExtractor,
    )

    custom = [
        SwTestPattern(
            name="widget_call",
            regex=r"\bwidget_(?P<module>[a-z][a-z0-9]*)_init\s*\(",
            confidence_tier="high",
        )
    ]
    pc = ProjectConventions(sw_test_patterns=custom)
    cfg = load_sw_test_config(None, project_conventions=pc)
    assert [p.name for p in cfg.patterns] == ["widget_call"]

    # End-to-end: extractor uses these custom patterns to resolve a
    # generic ``frobnicator`` module via a custom call shape.
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "test_frobnicator.c").write_text(
        "int main(void){ widget_frobnicator_init(); return 0; }\n"
    )
    ex = SWTestExtractor(
        known_entity_names=["frobnicator"], sw_test_config=cfg,
    )
    res = ex.extract(source=str(src_dir))
    edges = [t for t in res.triples if t.predicate == "tests_module"]
    assert any(t.object == "frobnicator" for t in edges)


# ---------------------------------------------------------------------------
# Phase 3 D2: generic markers exclude OTTF
# ---------------------------------------------------------------------------


def test_generic_default_markers_exclude_ottf():
    """The generic-default test-marker list contains ``int main(`` and
    ``void test_main(`` but NOT ``OTTF_DEFINE_TEST_CONFIG``."""
    from kgweave.knowledge_graph.common.sw_test_config import (
        GENERIC_DEFAULT_TEST_MARKERS,
        OPENTITAN_DEFAULT_TEST_MARKERS,
    )

    generic_patterns = [m.pattern for m in GENERIC_DEFAULT_TEST_MARKERS]
    ot_patterns = [m.pattern for m in OPENTITAN_DEFAULT_TEST_MARKERS]
    # Generic has the universal C/C++ entry points.
    assert any("int" in p and "main" in p for p in generic_patterns)
    assert any("test_main" in p for p in generic_patterns)
    # But NOT the OT-specific OTTF macro.
    assert not any("OTTF_DEFINE_TEST_CONFIG" in p for p in generic_patterns)
    # OT default still has it.
    assert any("OTTF_DEFINE_TEST_CONFIG" in p for p in ot_patterns)
