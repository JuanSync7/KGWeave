"""Phase 1 scaffolding: ProjectConventions dataclass on KGConfig.

These tests exercise *only* the dataclass plumbing — no extractor or reader
behavior change is permitted in Phase 1. Phase 2 wires consumers.
"""

from __future__ import annotations

import dataclasses
import warnings

import pytest

from kgweave.knowledge_graph.common.types import KGConfig, ProjectConventions


# ---------------------------------------------------------------------------
# Defaults / shape
# ---------------------------------------------------------------------------


def test_project_conventions_default_instantiation_all_generic():
    """A bare ProjectConventions() yields generic / None defaults — no OT bias."""
    pc = ProjectConventions()
    assert pc.profile is None
    assert pc.reset_signal_pattern is None
    assert pc.clock_signal_pattern is None
    assert pc.sva_prefixes is None
    assert pc.sva_suffixes is None
    assert pc.sw_test_patterns is None
    assert pc.sw_test_markers is None
    assert pc.csr_access_api_patterns is None
    assert pc.synthetic_csr_from_pattern is None
    assert pc.bazel_rule_allowlist is None
    assert pc.bazel_dep_module_pattern is None
    # Generic-but-conventional defaults from audit doc
    assert pc.csr_offset_suffixes == ["_REG_OFFSET", "_OFFSET"]
    assert pc.sw_test_extensions == [".c"]
    assert pc.makefile_module_vars == ["MODULE", "IP_NAME", "IP_TOP", "DUT", "DUT_NAME"]
    assert pc.makefile_test_target_prefixes == ["test-", "test_"]
    assert pc.makefile_module_strip_suffixes == ["_top", "_dut", "_core", "_wrapper"]
    assert pc.fusesoc_tb_target_hints == ["sim", "tb", "test"]
    assert pc.fusesoc_module_strip_suffixes == ["_sim", "_tb", "_test", "_dv"]
    assert pc.uvm_testbench_filename_suffix == "_tb.sv"
    assert pc.dv_test_file_strip_suffixes == ["_vseq.sv", "_test.sv", ".sv"]


def test_project_conventions_opentitan_classmethod_populates_ot_defaults():
    """ProjectConventions.opentitan() returns an instance with profile + OT shapes."""
    pc = ProjectConventions.opentitan()
    assert pc.profile == "opentitan"
    assert pc.reset_signal_pattern == r"(^|_)(rst|reset|por)(_|$)"
    assert pc.sva_prefixes == ["a_", "prim_", "aes_"]
    assert pc.bazel_rule_allowlist == [
        "opentitan_functest",
        "opentitan_test",
        "opentitan_binary",
        "cc_test",
        "cc_binary",
        "dv_lib",
        "dv_fusesoc_test",
    ]
    assert pc.bazel_dep_module_pattern == r"^//hw/ip/(?P<module>[a-z][a-z0-9_]*)\b"
    # Phase 2 wires actual sw_test patterns; Phase 1 leaves these None.
    assert pc.sw_test_patterns is None


def test_kgconfig_project_conventions_is_fresh_per_instance():
    """Each KGConfig() builds its own ProjectConventions — no shared mutable default."""
    a = KGConfig()
    b = KGConfig()
    assert isinstance(a.project_conventions, ProjectConventions)
    assert isinstance(b.project_conventions, ProjectConventions)
    assert a.project_conventions is not b.project_conventions


def test_kgconfig_round_trips_explicit_opentitan_conventions():
    """Passing ProjectConventions.opentitan() round-trips on KGConfig."""
    pc = ProjectConventions.opentitan()
    cfg = KGConfig(project_conventions=pc)
    assert cfg.project_conventions is pc
    assert cfg.project_conventions.profile == "opentitan"
    assert cfg.project_conventions.reset_signal_pattern == r"(^|_)(rst|reset|por)(_|$)"


# ---------------------------------------------------------------------------
# Deprecation shims
# ---------------------------------------------------------------------------


def test_deprecation_shim_reset_signal_pattern_warns_and_copies():
    """Setting legacy KGConfig.reset_signal_pattern emits DeprecationWarning AND
    populates project_conventions.reset_signal_pattern when the new field is None."""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = KGConfig(reset_signal_pattern="custom_rst_pat")
    deprecation = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert deprecation, "expected DeprecationWarning for legacy reset_signal_pattern"
    assert any(
        "project_conventions.reset_signal_pattern" in str(w.message) for w in deprecation
    )
    assert cfg.project_conventions.reset_signal_pattern == "custom_rst_pat"


def test_deprecation_shim_testplan_sva_prefixes_warns_and_copies():
    """Setting legacy KGConfig.testplan_sva_prefixes emits DeprecationWarning AND
    populates project_conventions.sva_prefixes."""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = KGConfig(testplan_sva_prefixes=["x_", "y_"])
    deprecation = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert deprecation, "expected DeprecationWarning for legacy testplan_sva_prefixes"
    assert any(
        "project_conventions.sva_prefixes" in str(w.message) for w in deprecation
    )
    assert cfg.project_conventions.sva_prefixes == ["x_", "y_"]


def test_deprecation_shim_does_not_overwrite_explicit_project_conventions():
    """If both legacy field AND project_conventions.* are set, the new field wins
    and no DeprecationWarning is emitted."""
    pc = ProjectConventions(
        reset_signal_pattern="new_rst",
        sva_prefixes=["new_"],
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = KGConfig(
            reset_signal_pattern="legacy_rst",
            testplan_sva_prefixes=["legacy_"],
            project_conventions=pc,
        )
    # New field wins.
    assert cfg.project_conventions.reset_signal_pattern == "new_rst"
    assert cfg.project_conventions.sva_prefixes == ["new_"]
    deprecation = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert not deprecation, (
        f"no DeprecationWarning expected when project_conventions populated, got {deprecation}"
    )


# ---------------------------------------------------------------------------
# Infra
# ---------------------------------------------------------------------------


def test_kgconfig_with_opentitan_conventions_is_serializable_via_asdict():
    """dataclasses.asdict on a KGConfig carrying ProjectConventions.opentitan() works
    end-to-end — no unhashable / non-dataclass field surprises."""
    cfg = KGConfig(project_conventions=ProjectConventions.opentitan())
    blob = dataclasses.asdict(cfg)
    assert isinstance(blob, dict)
    assert isinstance(blob["project_conventions"], dict)
    assert blob["project_conventions"]["profile"] == "opentitan"
    assert (
        blob["project_conventions"]["bazel_dep_module_pattern"]
        == r"^//hw/ip/(?P<module>[a-z][a-z0-9_]*)\b"
    )


# ---------------------------------------------------------------------------
# Phase 3 D10: generic SVA prefixes default excludes ``aes_``
# ---------------------------------------------------------------------------


def test_generic_sva_prefixes_default_excludes_aes():
    """Generic ProjectConventions has sva_prefixes=None; the testplan
    extractor's module-level fallback (``_SVA_PREFIXES``) must exclude
    project-specific prefixes like ``aes_``. Only the OT classmethod
    re-introduces ``aes_``."""
    from kgweave.knowledge_graph.extraction.testplan_extractor import _SVA_PREFIXES

    pc_generic = ProjectConventions()
    assert pc_generic.sva_prefixes is None
    # The module-level default must not carry project-specific OT prefixes.
    assert "aes_" not in _SVA_PREFIXES
    assert "a_" in _SVA_PREFIXES
    assert "prim_" in _SVA_PREFIXES

    pc_ot = ProjectConventions.opentitan()
    assert "aes_" in pc_ot.sva_prefixes
    assert "a_" in pc_ot.sva_prefixes
    assert "prim_" in pc_ot.sva_prefixes
