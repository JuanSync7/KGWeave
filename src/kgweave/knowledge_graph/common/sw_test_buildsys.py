# @summary
# Build-system ingestion framework (V3 Tier B) for SW→RTL test resolution.
# Defines BuildSystemLink + BuildSystemReader Protocol + discover_links()
# helper that aggregates links across registered readers. Format-specific
# parsers (dvsim hjson, UVM testlist .f, fusesoc .core, Bazel BUILD, GNU
# Makefile) live in sibling modules and register via the default reader
# list constructed from a SwTestBuildSystemConfig.
# Exports: BuildSystemLink, BuildSystemReader, discover_links,
#          default_readers, SwTestBuildSystemConfig
# Deps: dataclasses, pathlib, typing
# @end-summary
"""Build-system reader framework for the SW→RTL test resolver (Tier B).

When a project exposes machine-readable test→module links via its build
system (dvsim hjson, UVM testlists, fusesoc cores, Bazel BUILD files, or
GNU makefiles), those links are *authoritative* — the build system
actually compiles and runs the tests. They override any regex-pattern
match for the same ``(test_path, module_name)`` tuple.

Each format implements ``BuildSystemReader``:

  - ``name``: short identifier matching ``BuildSystemLink.source_format``
  - ``applies_to(project_root) -> bool``: cheap probe for relevant files
  - ``read(project_root) -> list[BuildSystemLink]``: parse and emit links

Use ``discover_links(project_root, readers=...)`` to run all enabled
readers and aggregate their output. Pass ``readers=None`` to use the
default registry (constructed from the in-process default config; only
``dvsim_hjson`` and ``bazel`` ship enabled, matching the OpenTitan
flavor).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

__all__ = [
    "BuildSystemLink",
    "BuildSystemReader",
    "SwTestBuildSystemConfig",
    "default_readers",
    "discover_links",
]

_logger = logging.getLogger("rag.knowledge_graph.sw_test_buildsys")


@dataclass
class BuildSystemLink:
    """A test→module link extracted from a build-system file.

    Attributes
    ----------
    test_path:
        Absolute path to the test source file (C, SV, or other).
    module_name:
        Canonical RTL module name as it appears in the KG.
    source_format:
        Short identifier for the producing reader; one of
        ``"dvsim_hjson" | "uvm_testlist" | "fusesoc" | "bazel" | "makefile"``.
    source_file:
        Absolute path to the build-system file the link came from
        (the .hjson / .f / .core / BUILD / Makefile).
    confidence_tier:
        ``"high"`` for machine-readable formats whose semantics directly
        encode test→module (dvsim, fusesoc, bazel). ``"medium"`` for
        heuristic formats (UVM testlist file-naming, Makefile variable
        scrape).
    raw_match:
        Free-form dict of the parsed entry, kept for debugging /
        evidence-span rendering.
    """

    test_path: str
    module_name: str
    source_format: str
    source_file: str
    confidence_tier: str
    raw_match: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class BuildSystemReader(Protocol):
    """Reader interface — five formats all implement this.

    Implementations should be cheap to construct and stateless across
    calls to ``read()`` so callers can pass them around freely.
    """

    name: str

    def applies_to(self, project_root: Path) -> bool:  # pragma: no cover - protocol
        ...

    def read(self, project_root: Path) -> List[BuildSystemLink]:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# Per-reader configuration. These mirror the YAML schema documented in
# config/sw_test_resolution.yaml under the ``build_systems:`` key.
# ---------------------------------------------------------------------------


@dataclass
class SwTestBuildSystemConfig:
    """Per-format on/off flags + glob/file overrides.

    Defaults: all readers disabled. The OpenTitan-flavored YAML enables
    ``dvsim_hjson`` and ``bazel`` to demonstrate end-to-end behavior on
    the AES dataset. In-process defaults stay fully off so existing
    callers that don't pass ``project_root`` see byte-identical
    behavior.
    """

    dvsim_hjson_enabled: bool = False
    dvsim_hjson_glob: str = "**/*_cfg.hjson"
    # V3 #2 — recursive ``import_cfgs:`` follow depth. Chip-level dvsim
    # cfgs typically have only 2-3 levels of nesting; the default of 5
    # leaves headroom for unusual setups while bounding worst-case work.
    dvsim_max_import_depth: int = 5

    uvm_testlist_enabled: bool = False
    uvm_testlist_glob: str = "**/*.f"

    fusesoc_enabled: bool = False
    fusesoc_glob: str = "**/*.core"

    bazel_enabled: bool = False
    bazel_files: List[str] = field(default_factory=lambda: ["BUILD", "BUILD.bazel"])
    # When None, the BazelBuildReader uses its built-in OpenTitan-flavored
    # default ``^//hw/ip/(?P<module>...)\b``. Override for projects with a
    # different label layout (e.g. ``^//rtl/(?P<module>...)\b``). Pattern
    # MUST contain a ``(?P<module>...)`` named group.
    bazel_dep_module_pattern: Optional[str] = None
    # V3 #3 — auto-discover macro names imported via Bazel `load()`
    # statements. When True (default), any symbol named in a `load(...)`
    # AND later called as a top-level rule with name+srcs+matching-deps is
    # treated as a candidate test rule. Conservative gating keeps it safe
    # by default; flip to False to fall back to allowlist-only behavior.
    bazel_auto_discover_loaded_macros: Optional[bool] = None
    # V3 #3 — symbols never auto-admitted even when load()-imported.
    # Useful for filtering out non-test rules pulled in from a shared
    # macro file (e.g. `cc_library`, `filegroup`).
    bazel_loaded_macro_denylist: Optional[List[str]] = None

    makefile_enabled: bool = False
    makefile_files: List[str] = field(
        default_factory=lambda: ["Makefile", "makefile", "*.mk"]
    )


def default_readers(
    config: Optional[SwTestBuildSystemConfig] = None,
    project_conventions: Optional[Any] = None,
) -> List[BuildSystemReader]:
    """Construct the default reader registry from a config.

    Imports each format module lazily so the framework is usable when
    individual readers are disabled (and so test failures in one reader
    don't poison the others).
    """
    cfg = config or SwTestBuildSystemConfig()
    readers: List[BuildSystemReader] = []

    if cfg.dvsim_hjson_enabled:
        try:
            from kgweave.knowledge_graph.extraction.buildsys_dvsim import (
                DvsimHjsonReader,
            )

            readers.append(DvsimHjsonReader(
                glob=cfg.dvsim_hjson_glob,
                max_import_depth=cfg.dvsim_max_import_depth,
            ))
        except ImportError as exc:
            _logger.warning("dvsim_hjson reader unavailable: %s", exc)

    if cfg.uvm_testlist_enabled:
        try:
            from kgweave.knowledge_graph.extraction.buildsys_uvm_testlist import (
                UvmTestlistReader,
            )

            uvm_kwargs: Dict[str, Any] = {"glob": cfg.uvm_testlist_glob}
            if project_conventions is not None:
                uvm_kwargs["project_conventions"] = project_conventions
            readers.append(UvmTestlistReader(**uvm_kwargs))
        except ImportError as exc:
            _logger.warning("uvm_testlist reader unavailable: %s", exc)

    if cfg.fusesoc_enabled:
        try:
            from kgweave.knowledge_graph.extraction.buildsys_fusesoc import (
                FusesocReader,
            )

            fusesoc_kwargs: Dict[str, Any] = {"glob": cfg.fusesoc_glob}
            if project_conventions is not None:
                fusesoc_kwargs["project_conventions"] = project_conventions
            readers.append(FusesocReader(**fusesoc_kwargs))
        except ImportError as exc:
            _logger.warning("fusesoc reader unavailable: %s", exc)

    if cfg.bazel_enabled:
        try:
            from kgweave.knowledge_graph.extraction.buildsys_bazel import (
                BazelBuildReader,
            )

            bazel_kwargs: Dict[str, Any] = {"files": cfg.bazel_files}
            if project_conventions is not None:
                bazel_kwargs["project_conventions"] = project_conventions
            if cfg.bazel_dep_module_pattern is not None:
                bazel_kwargs["dep_module_pattern"] = cfg.bazel_dep_module_pattern
            if cfg.bazel_auto_discover_loaded_macros is not None:
                bazel_kwargs["auto_discover_loaded_macros"] = (
                    cfg.bazel_auto_discover_loaded_macros
                )
            if cfg.bazel_loaded_macro_denylist is not None:
                bazel_kwargs["loaded_macro_denylist"] = (
                    cfg.bazel_loaded_macro_denylist
                )
            readers.append(BazelBuildReader(**bazel_kwargs))
        except ImportError as exc:
            _logger.warning("bazel reader unavailable: %s", exc)

    if cfg.makefile_enabled:
        try:
            from kgweave.knowledge_graph.extraction.buildsys_makefile import (
                MakefileReader,
            )

            mk_kwargs: Dict[str, Any] = {"files": cfg.makefile_files}
            if project_conventions is not None:
                mk_kwargs["project_conventions"] = project_conventions
            readers.append(MakefileReader(**mk_kwargs))
        except ImportError as exc:
            _logger.warning("makefile reader unavailable: %s", exc)

    return readers


def discover_links(
    project_root: Path,
    readers: Optional[List[BuildSystemReader]] = None,
) -> List[BuildSystemLink]:
    """Run all applicable readers; return aggregated links.

    Parameters
    ----------
    project_root:
        Directory at which to root each reader's discovery walk.
    readers:
        Explicit reader list (e.g. for tests). ``None`` selects the
        default registry built from a default-constructed
        ``SwTestBuildSystemConfig`` (everything off).
    """
    if readers is None:
        readers = default_readers()

    project_root = Path(project_root)
    out: List[BuildSystemLink] = []
    for reader in readers:
        try:
            if not reader.applies_to(project_root):
                continue
            links = reader.read(project_root)
        except Exception as exc:  # noqa: BLE001 — reader failures must not halt pipeline
            _logger.warning(
                "build-system reader %s failed on %s: %s",
                getattr(reader, "name", reader), project_root, exc,
            )
            continue
        if not links:
            continue
        out.extend(links)
    return out
