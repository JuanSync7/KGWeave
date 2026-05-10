# @summary
# Config-driven SW→RTL test resolution rules (V3 Tier A).
# Generic regex/transform patterns + test-file markers, loaded from YAML
# or constructed in-process. The OpenTitan defaults are baked in so the
# pipeline works without any YAML present.
# Exports: SwTestPattern, SwTestResolutionConfig, load_sw_test_config,
#          OPENTITAN_DEFAULT_PATTERNS, OPENTITAN_DEFAULT_TEST_MARKERS
# Deps: dataclasses, re, typing, yaml, pathlib
# @end-summary
"""Config-driven SW test resolver rules.

This module decouples the SW→RTL module resolver from OpenTitan-specific
string patterns. Project teams can point ``load_sw_test_config()`` at a
YAML describing their conventions (camelCase, vendor macros, no DIF
prefix, etc.) and the resolver will apply those patterns instead.

The OpenTitan defaults are intentionally baked into Python so the
resolver behaves identically when no YAML is supplied.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Pattern

import yaml

from kgweave.knowledge_graph.common.sw_test_buildsys import (
    SwTestBuildSystemConfig,
)
from kgweave.knowledge_graph.common.types import OPENTITAN_PROFILE

__all__ = [
    "SwTestPattern",
    "SwTestResolutionConfig",
    "load_sw_test_config",
    "OPENTITAN_DEFAULT_PATTERNS",
    "OPENTITAN_DEFAULT_TEST_MARKERS",
    "GENERIC_DEFAULT_TEST_MARKERS",
]

_logger = logging.getLogger("rag.knowledge_graph.sw_test_config")

VALID_TIERS = {"high", "medium", "low"}
VALID_TRANSFORMS = {"none", "lowercase", "uppercase"}


@dataclass
class SwTestPattern:
    """One named regex pattern for SW→RTL module resolution.

    Attributes
    ----------
    name:
        Pattern identifier (used in logs and evidence spans).
    regex:
        Either a string regex (compiled in ``__post_init__``) or a
        pre-compiled ``re.Pattern``. MUST contain a named group
        ``(?P<module>...)`` capturing the module name.
    confidence_tier:
        ``"high"`` / ``"medium"`` / ``"low"`` — propagated to emitted edges.
    transform:
        How to normalize the captured module name before lookup.
        ``"lowercase"`` (uppercase macros → lowercase module names),
        ``"uppercase"``, or ``"none"`` (default).
    description:
        Free-text purpose; not used at runtime.
    """

    name: str
    regex: Pattern  # accepts str at construction; compiled in __post_init__
    confidence_tier: str = "high"
    transform: str = "none"
    description: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.regex, str):
            self.regex = re.compile(self.regex)
        if "module" not in self.regex.groupindex:
            raise ValueError(
                f"SwTestPattern '{self.name}' regex must contain a named "
                f"group (?P<module>...); got pattern {self.regex.pattern!r}"
            )
        if self.confidence_tier not in VALID_TIERS:
            raise ValueError(
                f"SwTestPattern '{self.name}' has invalid confidence_tier "
                f"'{self.confidence_tier}'; must be one of {VALID_TIERS}"
            )
        if self.transform not in VALID_TRANSFORMS:
            raise ValueError(
                f"SwTestPattern '{self.name}' has invalid transform "
                f"'{self.transform}'; must be one of {VALID_TRANSFORMS}"
            )

    def apply_transform(self, module: str) -> str:
        if self.transform == "lowercase":
            return module.lower()
        if self.transform == "uppercase":
            return module.upper()
        return module


@dataclass
class SwTestResolutionConfig:
    """Full resolution config: patterns + test markers + flags."""

    patterns: List[SwTestPattern] = field(default_factory=list)
    test_markers: List[Pattern] = field(default_factory=list)
    preprocessor_strip_if_zero: bool = False
    build_systems: SwTestBuildSystemConfig = field(
        default_factory=SwTestBuildSystemConfig
    )

    def __post_init__(self) -> None:
        compiled: List[Pattern] = []
        for m in self.test_markers:
            if isinstance(m, str):
                compiled.append(re.compile(m))
            else:
                compiled.append(m)
        self.test_markers = compiled


# ---------------------------------------------------------------------------
# OpenTitan defaults
# ---------------------------------------------------------------------------

OPENTITAN_DEFAULT_PATTERNS: List[SwTestPattern] = [
    SwTestPattern(
        name="header_include",
        description='C test #include of an RTL DIF header (dif_<module>.h)',
        # captures the module portion of dif_<module>.h, allowing arbitrary
        # path prefixes
        regex=re.compile(r'#\s*include\s*[<"][^">]*?\bdif_(?P<module>[a-z][a-z0-9_]*)\.h[">]'),
        confidence_tier="high",
        transform="none",
    ),
    SwTestPattern(
        name="dif_api_call",
        description="OpenTitan DIF API call dispatching to a module",
        regex=re.compile(r"\bdif_(?P<module>[a-z][a-z0-9_]*?)_\w+\s*\("),
        confidence_tier="high",
        transform="none",
    ),
    SwTestPattern(
        name="base_addr_constant",
        description="Top-level base-address constant naming the module",
        # Suffix-anchored: must end with _<MODNAME>_BASE_ADDR with at least
        # one underscore-separated prefix segment (so AES_BASE_ADDR alone
        # without prefix doesn't satisfy this OpenTitan-specific pattern).
        regex=re.compile(r"\b[A-Z][A-Z0-9_]*?_(?P<module>[A-Z][A-Z0-9]*)_BASE_ADDR\b"),
        confidence_tier="high",
        transform="lowercase",
    ),
]

OPENTITAN_DEFAULT_TEST_MARKERS: List[Pattern] = [
    re.compile(r"\bint\s+main\s*\("),
    re.compile(r"\bvoid\s+test_main\s*\("),
    re.compile(r"\bOTTF_DEFINE_TEST_CONFIG\b"),
]

# Generic markers: portable C/C++ test entry points only — no OT-specific
# project macros. Used in strict-generic mode (no OT profile).
GENERIC_DEFAULT_TEST_MARKERS: List[Pattern] = [
    re.compile(r"\bint\s+main\s*\("),
    re.compile(r"\bvoid\s+test_main\s*\("),
]


def _opentitan_defaults(
    project_conventions: Optional[Any] = None,
    _suppress_profile_warning: bool = False,
) -> SwTestResolutionConfig:
    """Construct the OpenTitan-default config (mutable per-call copies).

    When this is reached and ``project_conventions`` is supplied with a
    profile other than ``"opentitan"``, emit a runtime WARNING — the
    OT defaults are about to be applied to a non-OT codebase, which is
    almost certainly going to silently produce zero-confidence noise.
    """
    if (
        not _suppress_profile_warning
        and project_conventions is not None
        and getattr(project_conventions, "profile", None) != "opentitan"
    ):
        _logger.warning(
            "sw_test_config: applying OpenTitan default patterns even though "
            "project_conventions.profile=%r. Set "
            "project_conventions=ProjectConventions.opentitan() to silence "
            "this warning, or supply explicit sw_test_patterns/YAML.",
            getattr(project_conventions, "profile", None),
        )
    return SwTestResolutionConfig(
        patterns=[
            SwTestPattern(
                name=p.name,
                regex=p.regex,
                confidence_tier=p.confidence_tier,
                transform=p.transform,
                description=p.description,
            )
            for p in OPENTITAN_DEFAULT_PATTERNS
        ],
        test_markers=list(OPENTITAN_DEFAULT_TEST_MARKERS),
        preprocessor_strip_if_zero=False,
    )


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def load_sw_test_config(
    path: Optional[str] = None,
    project_conventions: Optional[Any] = None,
) -> SwTestResolutionConfig:
    """Load a SW test resolution config.

    Resolution order:
      1. If *project_conventions.sw_test_patterns* is set, return a
         config built from those (explicit user override).
      2. If *path* is given AND the YAML exists, parse it (with OT
         defaults filling missing sections — preserves back-compat).
      3. If *path* is None or missing AND
         ``project_conventions.profile == "opentitan"``, return the OT
         defaults silently.
      4. Otherwise (strict-generic profile, no YAML) — return an EMPTY
         config and emit a WARNING. SW→RTL resolution will produce no
         pattern-based links.
    """
    # (1) explicit per-conventions override
    if project_conventions is not None:
        explicit_patterns = getattr(project_conventions, "sw_test_patterns", None)
        if explicit_patterns:
            markers = getattr(project_conventions, "sw_test_markers", None)
            if not markers:
                # Fall back to a profile-aware default.
                if getattr(project_conventions, "profile", None) == OPENTITAN_PROFILE:
                    markers = list(OPENTITAN_DEFAULT_TEST_MARKERS)
                else:
                    markers = list(GENERIC_DEFAULT_TEST_MARKERS)
            return SwTestResolutionConfig(
                patterns=list(explicit_patterns),
                test_markers=list(markers),
                preprocessor_strip_if_zero=False,
            )

    if not path:
        # (3) opentitan profile or legacy bare call → OT defaults.
        if project_conventions is None or (
            getattr(project_conventions, "profile", None) == OPENTITAN_PROFILE
        ):
            return _opentitan_defaults(
                project_conventions=project_conventions,
                _suppress_profile_warning=True,
            )
        # (4) strict-generic — empty config + warning.
        _logger.warning(
            "sw_test_config: no sw_test patterns configured "
            "(project_conventions.profile=%r and no YAML supplied). "
            "SW->RTL resolution will produce no links. Set "
            "project_conventions=ProjectConventions.%s() or supply "
            "an explicit YAML / sw_test_patterns.",
            getattr(project_conventions, "profile", None),
            OPENTITAN_PROFILE,
        )
        markers = getattr(project_conventions, "sw_test_markers", None)
        if not markers:
            markers = list(GENERIC_DEFAULT_TEST_MARKERS)
        return SwTestResolutionConfig(
            patterns=[],
            test_markers=list(markers),
            preprocessor_strip_if_zero=False,
        )

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        _logger.warning("SW test config not found at %s; using defaults", path)
        return _opentitan_defaults(
            project_conventions=project_conventions,
            _suppress_profile_warning=(project_conventions is None),
        )

    pattern_entries = raw.get("patterns")
    if pattern_entries is None:
        patterns = [
            SwTestPattern(
                name=p.name,
                regex=p.regex,
                confidence_tier=p.confidence_tier,
                transform=p.transform,
                description=p.description,
            )
            for p in OPENTITAN_DEFAULT_PATTERNS
        ]
    else:
        patterns = []
        for entry in pattern_entries:
            patterns.append(
                SwTestPattern(
                    name=entry["name"],
                    regex=entry["regex"],
                    confidence_tier=entry.get("confidence_tier", "high"),
                    transform=entry.get("transform", "none"),
                    description=entry.get("description", ""),
                )
            )

    marker_entries = raw.get("test_markers")
    if marker_entries is None:
        test_markers = list(OPENTITAN_DEFAULT_TEST_MARKERS)
    else:
        test_markers = [re.compile(m) for m in marker_entries]

    bs_raw = raw.get("build_systems") or {}
    bs_cfg = SwTestBuildSystemConfig()
    if isinstance(bs_raw, dict):
        for key, attr_prefix in (
            ("dvsim_hjson", "dvsim_hjson"),
            ("uvm_testlist", "uvm_testlist"),
            ("fusesoc", "fusesoc"),
            ("bazel", "bazel"),
            ("makefile", "makefile"),
        ):
            entry = bs_raw.get(key)
            if not isinstance(entry, dict):
                continue
            if "enabled" in entry:
                setattr(bs_cfg, f"{attr_prefix}_enabled", bool(entry["enabled"]))
            if "glob" in entry and isinstance(entry["glob"], str):
                if hasattr(bs_cfg, f"{attr_prefix}_glob"):
                    setattr(bs_cfg, f"{attr_prefix}_glob", entry["glob"])
            if "files" in entry and isinstance(entry["files"], list):
                if hasattr(bs_cfg, f"{attr_prefix}_files"):
                    setattr(bs_cfg, f"{attr_prefix}_files",
                            [str(f) for f in entry["files"]])
            if key == "bazel" and "dep_module_pattern" in entry:
                pat = entry["dep_module_pattern"]
                if isinstance(pat, str):
                    bs_cfg.bazel_dep_module_pattern = pat
            if key == "bazel" and "auto_discover_loaded_macros" in entry:
                ad = entry["auto_discover_loaded_macros"]
                if isinstance(ad, bool):
                    bs_cfg.bazel_auto_discover_loaded_macros = ad
            if key == "bazel" and "loaded_macro_denylist" in entry:
                dl = entry["loaded_macro_denylist"]
                if isinstance(dl, list):
                    bs_cfg.bazel_loaded_macro_denylist = [str(x) for x in dl]
            if key == "dvsim_hjson" and "max_import_depth" in entry:
                depth = entry["max_import_depth"]
                if isinstance(depth, int) and depth >= 0:
                    bs_cfg.dvsim_max_import_depth = depth

    return SwTestResolutionConfig(
        patterns=patterns,
        test_markers=test_markers,
        preprocessor_strip_if_zero=bool(raw.get("preprocessor_strip_if_zero", False)),
        build_systems=bs_cfg,
    )
