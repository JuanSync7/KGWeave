"""Tier B Phase 5: Bazel BUILD reader tests."""
from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import dedent

import pytest


def _w(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(body))
    return p


# ---------------------------------------------------------------------------
# (1) opentitan_functest with srcs + deps → links emitted
# ---------------------------------------------------------------------------


def test_bazel_opentitan_functest_basic(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        opentitan_functest(
            name = "aes_smoketest",
            srcs = ["aes_smoketest.c"],
            deps = [
                "//hw/ip/aes:aes_pkg",
                "//sw/device/lib/dif:aes",
            ],
        )
        ''')
    reader = BazelBuildReader()
    assert reader.applies_to(tmp_path) is True
    links = reader.read(tmp_path)
    assert links, "expected ≥1 link"
    assert {l.module_name for l in links} == {"aes"}
    assert {l.source_format for l in links} == {"bazel"}
    assert {l.confidence_tier for l in links} == {"high"}
    test_files = {Path(l.test_path).name for l in links}
    assert "aes_smoketest.c" in test_files


# ---------------------------------------------------------------------------
# (2) Multiple deps → multiple module links from same test
# ---------------------------------------------------------------------------


def test_bazel_multiple_module_deps(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD", '''
        opentitan_functest(
            name = "x_test",
            srcs = ["x_test.c"],
            deps = [
                "//hw/ip/aes:dif",
                "//hw/ip/hmac:dif",
                "//some/other:thing",
            ],
        )
        ''')
    links = BazelBuildReader().read(tmp_path)
    mods = {l.module_name for l in links}
    assert "aes" in mods
    assert "hmac" in mods


# ---------------------------------------------------------------------------
# (3) Other rule kinds (e.g. cc_test) honored when in allowlist
# ---------------------------------------------------------------------------


def test_bazel_cc_test_rule(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        cc_test(
            name = "aes_unit",
            srcs = ["aes_unit_test.cc"],
            deps = ["//hw/ip/aes:lib"],
        )
        ''')
    reader = BazelBuildReader(rule_allowlist=["cc_test", "opentitan_functest"])
    links = reader.read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"aes"}


# ---------------------------------------------------------------------------
# (4) Rule outside allowlist is ignored
# ---------------------------------------------------------------------------


def test_bazel_rule_outside_allowlist(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD", '''
        unrelated_rule(
            name = "x",
            srcs = ["x.c"],
            deps = ["//hw/ip/aes:lib"],
        )
        ''')
    links = BazelBuildReader().read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (5) Real OpenTitan AES BUILD file (skipped if absent)
# ---------------------------------------------------------------------------


def test_real_opentitan_aes_bazel(tmp_path):
    real_build = (
        Path.home() / "RagWeave" / "opentitan_data"
        / "sw" / "device" / "tests" / "BUILD"
    )
    if not real_build.exists():
        pytest.skip("OpenTitan AES BUILD not present")

    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    staged = tmp_path / "sw" / "device" / "tests"
    staged.mkdir(parents=True)
    shutil.copy(real_build, staged / "BUILD")
    links = BazelBuildReader().read(tmp_path)
    aes_links = [l for l in links if l.module_name == "aes"]
    # OT has many opentitan_test rules with `//hw/ip/aes:...` deps.
    assert len(aes_links) >= 5, f"expected ≥5 aes-bazel links, got {len(aes_links)}"
    test_basenames = {Path(l.test_path).name for l in aes_links}
    # Should at least find the smoketest.
    assert any("aes" in tn for tn in test_basenames)


# ---------------------------------------------------------------------------
# (6) Vanilla cc_test (non-OpenTitan flavor) extracted via default allowlist
# ---------------------------------------------------------------------------


def test_bazel_vanilla_cc_test(tmp_path):
    """A plain Bazel ``cc_test(...)`` with srcs/deps in the default
    allowlist works without any OpenTitan-specific configuration."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        cc_test(
            name = "aes_core_test",
            srcs = ["aes_core_test.cc"],
            deps = [
                "//hw/ip/aes:core_lib",
                "//third_party/gtest:main",
            ],
        )
        ''')
    links = BazelBuildReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"aes"}
    assert any(Path(l.test_path).name == "aes_core_test.cc" for l in links)


# ---------------------------------------------------------------------------
# (7) Macro-loaded rule via load("//macros:hw.bzl", "sv_test")
# ---------------------------------------------------------------------------


def test_bazel_load_then_macro_call(tmp_path):
    """A BUILD file may load a custom rule from a .bzl file then call it.
    The reader is regex-only and only sees direct rule-call sites; we
    verify the load() statement itself doesn't break parsing and that
    when sv_test is added to the allowlist it is recognised."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        load("//macros:hw.bzl", "sv_test", "sv_library")
        load("@rules_cc//cc:defs.bzl", "cc_library")

        sv_test(
            name = "hmac_smoke",
            srcs = ["hmac_smoke_tb.sv"],
            deps = ["//hw/ip/hmac:rtl"],
        )
        ''')
    reader = BazelBuildReader(rule_allowlist=["sv_test", "opentitan_functest"])
    links = reader.read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"hmac"}


# ---------------------------------------------------------------------------
# (8) Non-test rules in same file are silently skipped (no false positives)
# ---------------------------------------------------------------------------


def test_bazel_non_test_rules_skipped(tmp_path):
    """A BUILD file mixing dv_lib, cc_library, filegroup, package_group,
    exports_files alongside a test rule must only produce a link for the
    test rule. The non-test rules contain `//hw/ip/foo:...` references
    that would be false positives if blindly extracted."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD", '''
        package_group(
            name = "internal",
            packages = ["//hw/ip/aes/..."],
        )

        exports_files(["aes_helper.h"])

        filegroup(
            name = "aes_data",
            srcs = ["data.bin"],
        )

        cc_library(
            name = "aes_helper_lib",
            srcs = ["aes_helper.cc"],
            deps = ["//hw/ip/aes:core"],
        )

        opentitan_functest(
            name = "aes_real_test",
            srcs = ["aes_real_test.c"],
            deps = ["//hw/ip/aes:dif"],
        )
        ''')
    links = BazelBuildReader().read(tmp_path)
    # Only the opentitan_functest contributes; cc_library is not in default
    # allowlist (only cc_test is).
    test_files = {Path(l.test_path).name for l in links}
    assert "aes_real_test.c" in test_files
    assert "aes_helper.cc" not in test_files


# ---------------------------------------------------------------------------
# (9) Multi-rule BUILD: several rules in one file → independent links
# ---------------------------------------------------------------------------


def test_bazel_multi_rule_build_file(tmp_path):
    """A single BUILD.bazel may declare many rules. Each in-allowlist rule
    gets its own link set."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        opentitan_functest(
            name = "aes_t1",
            srcs = ["aes_t1.c"],
            deps = ["//hw/ip/aes:dif"],
        )

        opentitan_functest(
            name = "aes_t2",
            srcs = ["aes_t2.c"],
            deps = ["//hw/ip/aes:dif"],
        )

        opentitan_functest(
            name = "hmac_t",
            srcs = ["hmac_t.c"],
            deps = ["//hw/ip/hmac:dif"],
        )
        ''')
    links = BazelBuildReader().read(tmp_path)
    test_files = {Path(l.test_path).name for l in links}
    assert "aes_t1.c" in test_files
    assert "aes_t2.c" in test_files
    assert "hmac_t.c" in test_files
    mods = {l.module_name for l in links}
    assert mods == {"aes", "hmac"}


# ---------------------------------------------------------------------------
# (10) BUILD vs BUILD.bazel filename equivalence
# ---------------------------------------------------------------------------


def test_bazel_build_filename_alternatives(tmp_path):
    """Both ``BUILD`` and ``BUILD.bazel`` are scanned by default."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "a" / "BUILD", '''
        opentitan_functest(
            name = "ta",
            srcs = ["ta.c"],
            deps = ["//hw/ip/aes:dif"],
        )
        ''')
    _w(tmp_path / "b" / "BUILD.bazel", '''
        opentitan_functest(
            name = "tb",
            srcs = ["tb.c"],
            deps = ["//hw/ip/hmac:dif"],
        )
        ''')
    links = BazelBuildReader().read(tmp_path)
    test_files = {Path(l.test_path).name for l in links}
    assert "ta.c" in test_files
    assert "tb.c" in test_files


# ---------------------------------------------------------------------------
# (11) Custom dep_module_pattern: non-OpenTitan //rtl/<module> layout
# ---------------------------------------------------------------------------


def test_bazel_custom_dep_module_pattern_rtl_layout(tmp_path):
    """Constructor-configurable ``dep_module_pattern`` lets a non-OT project
    using ``//rtl/<module>:...`` deps attribute tests to RTL modules."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        cc_test(
            name = "aes_unit",
            srcs = ["aes_unit.cc"],
            deps = [
                "//rtl/aes:rtl",
                "//third_party/gtest:main",
            ],
        )
        ''')
    reader = BazelBuildReader(
        dep_module_pattern=r'^//rtl/(?P<module>[a-z][a-z0-9_]*)\b',
    )
    links = reader.read(tmp_path)
    assert links, "expected ≥1 link from //rtl/<module> deps"
    assert {l.module_name for l in links} == {"aes"}


# ---------------------------------------------------------------------------
# (12) Default dep_module_pattern: existing OT behavior preserved
# ---------------------------------------------------------------------------


def test_bazel_default_dep_module_pattern_preserves_ot_behavior(tmp_path):
    """Default-constructed reader still extracts modules from
    ``//hw/ip/<module>:...`` deps (no regression)."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        opentitan_functest(
            name = "aes_default_test",
            srcs = ["aes_default_test.c"],
            deps = ["//hw/ip/aes:dif"],
        )
        ''')
    links = BazelBuildReader().read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"aes"}


# ---------------------------------------------------------------------------
# (13) Pattern lacking (?P<module>...) named group raises ValueError
# ---------------------------------------------------------------------------


def test_bazel_dep_module_pattern_missing_module_group_raises():
    """A pattern without a ``module`` named group must be rejected at
    construction with a clear error message."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    with pytest.raises(ValueError, match="module"):
        BazelBuildReader(dep_module_pattern=r'^//rtl/([a-z][a-z0-9_]*)\b')


# ---------------------------------------------------------------------------
# (14) YAML round-trip: bazel_dep_module_pattern flows into reader
# ---------------------------------------------------------------------------


def test_bazel_dep_module_pattern_yaml_roundtrip(tmp_path):
    """A YAML config with ``build_systems.bazel.dep_module_pattern`` round-trips
    into ``SwTestBuildSystemConfig.bazel_dep_module_pattern`` and the reader
    constructed via ``default_readers()`` uses it."""
    from kgweave.knowledge_graph.common.sw_test_config import load_sw_test_config
    from kgweave.knowledge_graph.common.sw_test_buildsys import default_readers
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    yml = tmp_path / "cfg.yaml"
    yml.write_text(dedent('''
        build_systems:
          bazel:
            enabled: true
            dep_module_pattern: '^//rtl/(?P<module>[a-z][a-z0-9_]*)\\b'
    '''))
    cfg = load_sw_test_config(str(yml))
    assert cfg.build_systems.bazel_dep_module_pattern == \
        r'^//rtl/(?P<module>[a-z][a-z0-9_]*)\b'

    readers = default_readers(cfg.build_systems)
    bazel_readers = [r for r in readers if isinstance(r, BazelBuildReader)]
    assert len(bazel_readers) == 1

    proj = tmp_path / "proj"
    _w(proj / "BUILD.bazel", '''
        cc_test(
            name = "hmac_unit",
            srcs = ["hmac_unit.cc"],
            deps = ["//rtl/hmac:rtl"],
        )
        ''')
    links = bazel_readers[0].read(proj)
    assert links
    assert {l.module_name for l in links} == {"hmac"}


# ---------------------------------------------------------------------------
# (15) V3 #3 — auto-discovered loaded macro emits link with provenance tags
# ---------------------------------------------------------------------------


def test_bazel_loaded_macro_auto_discovery(tmp_path):
    """A `load("//macros:hw.bzl", "sv_test")` followed by an `sv_test(...)`
    call with name+srcs+matching deps should auto-discover the rule and
    emit a link tagged with `bazel_rule_origin="loaded_macro"` and
    `bazel_loaded_from="//macros:hw.bzl"`."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        load("//macros:hw.bzl", "sv_test", "sv_smoke_test")

        sv_test(
            name = "aes_smoke",
            srcs = ["aes_smoke.sv"],
            deps = ["//hw/ip/aes:rtl"],
        )
        ''')
    reader = BazelBuildReader()
    links = reader.read(tmp_path)
    assert links, "expected ≥1 auto-discovered link"
    assert {l.module_name for l in links} == {"aes"}
    link = links[0]
    attrs = getattr(link, "attributes", None) or link.raw_match.get("attributes", {})
    # Provenance must indicate auto-discovery
    assert attrs.get("bazel_rule_origin") == "loaded_macro"
    assert attrs.get("bazel_loaded_from") == "//macros:hw.bzl"


# ---------------------------------------------------------------------------
# (16) V3 #3 — gating: loaded macro call w/o matching deps → no link
# ---------------------------------------------------------------------------


def test_bazel_loaded_macro_gated_no_matching_deps(tmp_path):
    """An `sv_test(...)` whose deps don't match the dep_module_pattern is
    gated out silently (no error, no link)."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        load("//macros:hw.bzl", "sv_test")

        sv_test(
            name = "aes_smoke",
            srcs = ["aes_smoke.sv"],
            deps = ["//third_party/somelib:foo"],
        )
        ''')
    reader = BazelBuildReader()
    links = reader.read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (17) V3 #3 — gating: loaded macro call w/o srcs+deps → no link
# ---------------------------------------------------------------------------


def test_bazel_loaded_macro_gated_structural_shape(tmp_path):
    """A loaded-macro call with `name` only (no srcs, no deps) is not a
    test/binary shape and is gated out."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        load("//macros:hw.bzl", "sv_test")

        sv_test(
            name = "aes_smoke",
        )
        ''')
    reader = BazelBuildReader()
    links = reader.read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (18) V3 #3 — loaded_macro_denylist blocks auto-discovery
# ---------------------------------------------------------------------------


def test_bazel_loaded_macro_denylist(tmp_path):
    """`loaded_macro_denylist` prevents auto-admit of named symbols even
    when load()-imported and shape-matching."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        load("//macros:hw.bzl", "cc_library")

        cc_library(
            name = "aes_helper",
            srcs = ["aes_helper.cc"],
            deps = ["//hw/ip/aes:core"],
        )
        ''')
    reader = BazelBuildReader(loaded_macro_denylist=["cc_library"])
    links = reader.read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (19) V3 #3 — auto_discover_loaded_macros=False disables the feature
# ---------------------------------------------------------------------------


def test_bazel_auto_discover_disabled(tmp_path):
    """With `auto_discover_loaded_macros=False`, only allowlist matches
    emit. A loaded `sv_test` call is silently ignored."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        load("//macros:hw.bzl", "sv_test")

        sv_test(
            name = "aes_smoke",
            srcs = ["aes_smoke.sv"],
            deps = ["//hw/ip/aes:rtl"],
        )

        opentitan_functest(
            name = "aes_real",
            srcs = ["aes_real.c"],
            deps = ["//hw/ip/aes:dif"],
        )
        ''')
    reader = BazelBuildReader(auto_discover_loaded_macros=False)
    links = reader.read(tmp_path)
    # Only the allowlist match survives
    test_files = {Path(l.test_path).name for l in links}
    assert "aes_smoke.sv" not in test_files
    assert "aes_real.c" in test_files


# ---------------------------------------------------------------------------
# (20) V3 #3 — allowlist hit gets bazel_rule_origin="allowlist" tag
# ---------------------------------------------------------------------------


def test_bazel_allowlist_origin_tag(tmp_path):
    """Existing allowlist behavior is preserved; emitted links are tagged
    with `bazel_rule_origin="allowlist"`."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        opentitan_functest(
            name = "aes_real",
            srcs = ["aes_real.c"],
            deps = ["//hw/ip/aes:dif"],
        )
        ''')
    links = BazelBuildReader().read(tmp_path)
    assert links
    link = links[0]
    attrs = getattr(link, "attributes", None) or link.raw_match.get("attributes", {})
    assert attrs.get("bazel_rule_origin") == "allowlist"


# ---------------------------------------------------------------------------
# (21) V3 #3 — YAML round-trip: bazel_auto_discover_loaded_macros: false
# ---------------------------------------------------------------------------


def test_bazel_auto_discover_yaml_roundtrip(tmp_path):
    """`build_systems.bazel.auto_discover_loaded_macros: false` flows into
    `SwTestBuildSystemConfig.bazel_auto_discover_loaded_macros` and through
    to the constructed reader."""
    from kgweave.knowledge_graph.common.sw_test_config import load_sw_test_config
    from kgweave.knowledge_graph.common.sw_test_buildsys import default_readers
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    yml = tmp_path / "cfg.yaml"
    yml.write_text(dedent('''
        build_systems:
          bazel:
            enabled: true
            auto_discover_loaded_macros: false
    '''))
    cfg = load_sw_test_config(str(yml))
    assert cfg.build_systems.bazel_auto_discover_loaded_macros is False

    readers = default_readers(cfg.build_systems)
    bazel_readers = [r for r in readers if isinstance(r, BazelBuildReader)]
    assert len(bazel_readers) == 1

    proj = tmp_path / "proj"
    _w(proj / "BUILD.bazel", '''
        load("//macros:hw.bzl", "sv_test")

        sv_test(
            name = "aes_smoke",
            srcs = ["aes_smoke.sv"],
            deps = ["//hw/ip/aes:rtl"],
        )
        ''')
    links = bazel_readers[0].read(proj)
    assert links == []  # auto-discovery disabled via YAML


# ---------------------------------------------------------------------------
# (22) V3 #3 — YAML round-trip: bazel_loaded_macro_denylist
# ---------------------------------------------------------------------------


def test_bazel_loaded_macro_denylist_yaml_roundtrip(tmp_path):
    """`build_systems.bazel.loaded_macro_denylist: [cc_library]` flows
    through and prevents auto-discovery of `cc_library`."""
    from kgweave.knowledge_graph.common.sw_test_config import load_sw_test_config
    from kgweave.knowledge_graph.common.sw_test_buildsys import default_readers
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    yml = tmp_path / "cfg.yaml"
    yml.write_text(dedent('''
        build_systems:
          bazel:
            enabled: true
            loaded_macro_denylist: ["cc_library"]
    '''))
    cfg = load_sw_test_config(str(yml))
    assert cfg.build_systems.bazel_loaded_macro_denylist == ["cc_library"]

    readers = default_readers(cfg.build_systems)
    bazel_readers = [r for r in readers if isinstance(r, BazelBuildReader)]
    assert len(bazel_readers) == 1

    proj = tmp_path / "proj"
    _w(proj / "BUILD.bazel", '''
        load("//macros:hw.bzl", "cc_library")

        cc_library(
            name = "aes_helper",
            srcs = ["aes_helper.cc"],
            deps = ["//hw/ip/aes:core"],
        )
        ''')
    links = bazel_readers[0].read(proj)
    assert links == []


# ---------------------------------------------------------------------------
# (23) V3 #3 — integration: discover_links over multi-file fixture
# ---------------------------------------------------------------------------


def test_bazel_auto_discovery_integration_multifile(tmp_path):
    """End-to-end via discover_links: one BUILD with allowlist call, one
    with load()+macro, one with both. All survive with proper origin tags."""
    from kgweave.knowledge_graph.common.sw_test_buildsys import (
        SwTestBuildSystemConfig,
        default_readers,
        discover_links,
    )

    # Allowlist-only BUILD
    _w(tmp_path / "a" / "BUILD", '''
        opentitan_functest(
            name = "ta",
            srcs = ["ta.c"],
            deps = ["//hw/ip/aes:dif"],
        )
        ''')
    # Loaded-macro-only BUILD
    _w(tmp_path / "b" / "BUILD.bazel", '''
        load("//macros:hw.bzl", "sv_test")

        sv_test(
            name = "tb",
            srcs = ["tb.sv"],
            deps = ["//hw/ip/hmac:rtl"],
        )
        ''')
    # Mixed BUILD
    _w(tmp_path / "c" / "BUILD.bazel", '''
        load("//macros:hw.bzl", "sv_test")

        opentitan_functest(
            name = "tc1",
            srcs = ["tc1.c"],
            deps = ["//hw/ip/aes:dif"],
        )
        sv_test(
            name = "tc2",
            srcs = ["tc2.sv"],
            deps = ["//hw/ip/hmac:rtl"],
        )
        ''')

    cfg = SwTestBuildSystemConfig(bazel_enabled=True)
    readers = default_readers(cfg)
    links = discover_links(tmp_path, readers=readers)

    by_test: dict[str, dict] = {}
    for l in links:
        attrs = getattr(l, "attributes", None) or l.raw_match.get("attributes", {})
        by_test[Path(l.test_path).name] = {
            "module": l.module_name,
            "origin": attrs.get("bazel_rule_origin"),
        }
    assert by_test["ta.c"] == {"module": "aes", "origin": "allowlist"}
    assert by_test["tb.sv"] == {"module": "hmac", "origin": "loaded_macro"}
    assert by_test["tc1.c"] == {"module": "aes", "origin": "allowlist"}
    assert by_test["tc2.sv"] == {"module": "hmac", "origin": "loaded_macro"}


# ---------------------------------------------------------------------------
# Phase 2 — generic non-OT layout via project_conventions
# ---------------------------------------------------------------------------


def test_bazel_project_conventions_generic_rtl_widget_layout(tmp_path):
    """A project_conventions overlay supplying a non-OT
    ``//rtl/(?P<module>...)`` pattern picks up a generic ``//rtl/widget:rtl``
    dep without any OT-flavored hardcoded fallback."""
    from kgweave.knowledge_graph.common.types import ProjectConventions
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        cc_test(
            name = "widget_unit",
            srcs = ["widget_unit.cc"],
            deps = ["//rtl/widget:rtl"],
        )
        ''')
    pc = ProjectConventions(
        bazel_dep_module_pattern=r"^//rtl/(?P<module>[a-z][a-z0-9_]*)\b",
    )
    reader = BazelBuildReader(project_conventions=pc)
    links = reader.read(tmp_path)
    assert links
    assert {l.module_name for l in links} == {"widget"}


def test_bazel_strict_generic_conventions_emits_zero_module_links(tmp_path, caplog):
    """When ProjectConventions is supplied with no bazel_dep_module_pattern
    (strict-generic profile), the reader emits zero module links and logs a
    warning — rather than silently falling back to the OT pattern."""
    import logging

    from kgweave.knowledge_graph.common.types import ProjectConventions
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader

    _w(tmp_path / "BUILD.bazel", '''
        cc_test(
            name = "frobnicator_unit",
            srcs = ["frobnicator_unit.cc"],
            deps = ["//rtl/frobnicator:rtl"],
        )
        ''')
    pc = ProjectConventions()  # strict-generic, profile=None
    with caplog.at_level(logging.WARNING, logger="rag.knowledge_graph.buildsys_bazel"):
        reader = BazelBuildReader(project_conventions=pc)
    # Warning fires at construction time
    assert any(
        "no dep_module_pattern" in rec.getMessage().lower()
        or "bazel deps will not produce" in rec.getMessage().lower()
        for rec in caplog.records
    )
    links = reader.read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# Phase 3 D1: generic-only allowlist excludes OT rules
# ---------------------------------------------------------------------------


def test_bazel_generic_allowlist_excludes_ot_rules(tmp_path):
    """When ProjectConventions is supplied without a bazel_rule_allowlist,
    the reader falls back to the generic ``cc_test``/``cc_binary`` set,
    excluding OT-flavoured rules like ``opentitan_functest``."""
    from kgweave.knowledge_graph.extraction.buildsys_bazel import BazelBuildReader
    from kgweave.knowledge_graph.common.types import ProjectConventions

    _w(tmp_path / "BUILD.bazel", '''
        opentitan_functest(
            name = "frobnicator_smoke",
            srcs = ["frobnicator_smoke.c"],
            deps = ["//hw/ip/frobnicator:frobnicator_pkg"],
        )
        cc_test(
            name = "widget_unit",
            srcs = ["widget_unit.c"],
            deps = ["//hw/ip/widget:widget_pkg"],
        )
        ''')
    pc = ProjectConventions(
        bazel_dep_module_pattern=r"^//hw/ip/(?P<module>[a-z][a-z0-9_]*)\b",
    )
    reader = BazelBuildReader(project_conventions=pc)
    links = reader.read(tmp_path)
    mods = {l.module_name for l in links}
    # cc_test seen, opentitan_functest skipped.
    assert "widget" in mods
    assert "frobnicator" not in mods
