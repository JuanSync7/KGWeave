# @summary
# fusesoc .core reader (Tier B Phase 4). Parses CAPI2 YAML core files
# and emits one BuildSystemLink per tb fileset source. Module name is
# derived from the VLNV `name:` field (vendor:lib:CORE:ver where CORE
# is parsed for its leading identifier — `aes_sim` → `aes`,
# `hmac_sim` → `hmac`). Confidence tier: high.
# Exports: FusesocReader
# Deps: yaml, pathlib, kgweave.knowledge_graph.common.sw_test_buildsys
# @end-summary
"""fusesoc CAPI2 .core reader."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional, Sequence

import yaml

from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink

__all__ = ["FusesocReader"]

_logger = logging.getLogger("rag.knowledge_graph.buildsys_fusesoc")

# Identifies "this target builds a testbench/sim". Heuristic: target name
# contains 'sim'/'tb'/'test'/'verilator', or its toplevel field is 'tb'.
_DEFAULT_TB_TARGET_HINTS = ("sim", "tb", "test", "verilator")
# Within a tb-style target, fileset names that look like RTL-only (rtl,
# core, rtl_only) should be skipped — those files are the DUT, not the
# test source. We still keep the target's fileset list as a candidate
# pool but filter using these substrings on the *fileset* name.
_RTL_ONLY_FILESET_HINTS = ("rtl", "core")
_RTL_ONLY_FILESET_NAMES = {"rtl", "core", "rtl_only", "rtl_files"}
_DEFAULT_MODULE_STRIP_SUFFIXES = ("_sim", "_tb", "_test", "_dv")


def _strip_suffixes(core: str, suffixes: tuple) -> str:
    """Strip the first matching suffix from *core* and return the result.
    Iterates *suffixes* in order; returns *core* unchanged if none match."""
    for sfx in suffixes:
        if core.endswith(sfx):
            stripped = core[: -len(sfx)]
            return stripped if stripped else core
    return core


def _module_from_vlnv(
    name_field: str,
    strip_suffixes: Optional[tuple] = None,
) -> Optional[str]:
    """Best-effort RTL module extractor from a VLNV name.

    VLNV format: ``vendor:lib:core[:ver]``.  We extract the *core* segment
    using a plain ``str.split(":")`` — no regex needed for a colon-delimited
    field.
    """
    if not name_field:
        return None
    parts = name_field.strip().split(":")
    # VLNV has at least 3 parts (vendor:lib:core); fall back to last segment.
    core = parts[2] if len(parts) >= 3 else parts[-1]
    if not core:
        return None
    # Strip well-known suffixes (aes_sim → aes, hmac_dv → hmac).
    suffixes = strip_suffixes if strip_suffixes is not None else _DEFAULT_MODULE_STRIP_SUFFIXES
    return _strip_suffixes(core, tuple(suffixes))


def _is_tb_target(
    target_name: str,
    target_data: dict,
    tb_hints: Sequence[str] = _DEFAULT_TB_TARGET_HINTS,
) -> bool:
    name_low = target_name.lower()
    if any(h in name_low for h in tb_hints):
        return True
    toplevel = target_data.get("toplevel") or ""
    if isinstance(toplevel, str) and toplevel.lower() in ("tb", "testbench"):
        return True
    return False


class FusesocReader:
    """Reader for fusesoc CAPI2 .core YAML files."""

    name = "fusesoc"

    def __init__(
        self,
        glob: str = "**/*.core",
        tb_target_hints: Optional[Sequence[str]] = None,
        module_strip_suffixes: Optional[Sequence[str]] = None,
        project_conventions: Optional[Any] = None,
    ) -> None:
        self._glob = glob

        # Resolve tb_target_hints.
        if tb_target_hints is None and project_conventions is not None:
            pc = getattr(project_conventions, "fusesoc_tb_target_hints", None)
            if pc:
                tb_target_hints = pc
        self._tb_hints: tuple = tuple(tb_target_hints) if tb_target_hints else _DEFAULT_TB_TARGET_HINTS

        # Resolve module_strip_suffixes — stored as a plain tuple, no regex.
        if module_strip_suffixes is None and project_conventions is not None:
            pc_sfx = getattr(project_conventions, "fusesoc_module_strip_suffixes", None)
            if pc_sfx:
                module_strip_suffixes = pc_sfx
        self._module_strip_suffixes: Optional[tuple] = (
            tuple(module_strip_suffixes) if module_strip_suffixes else None
        )

    def applies_to(self, project_root: Path) -> bool:
        try:
            return next(project_root.glob(self._glob), None) is not None
        except OSError:
            return False

    def read(self, project_root: Path) -> List[BuildSystemLink]:
        out: List[BuildSystemLink] = []
        for core_path in sorted(project_root.glob(self._glob)):
            out.extend(self._read_one(core_path))
        return out

    def _read_one(self, core_path: Path) -> List[BuildSystemLink]:
        try:
            text = core_path.read_text(errors="replace")
        except OSError as exc:
            _logger.warning("fusesoc: cannot read %s: %s", core_path, exc)
            return []
        # CAPI=2: header is technically not YAML — fusesoc strips it. Try
        # both with and without removing the first line.
        if text.startswith("CAPI=2:"):
            yaml_text = text.split("\n", 1)[1] if "\n" in text else ""
        elif text.lstrip().startswith("CAPI=1"):
            # CAPI=1 is the legacy INI-style format. Not supported here —
            # fusesoc itself dropped support long ago. Log + skip.
            _logger.warning(
                "fusesoc: CAPI=1 core file is unsupported, skipping: %s",
                core_path,
            )
            return []
        else:
            yaml_text = text
        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            _logger.warning("fusesoc: malformed YAML at %s: %s", core_path, exc)
            return []
        if not isinstance(data, dict):
            return []
        module = _module_from_vlnv(data.get("name", ""), self._module_strip_suffixes)
        if not module:
            return []
        targets = data.get("targets") or {}
        if not isinstance(targets, dict):
            return []
        # Identify tb-style targets and the filesets they reference.
        tb_filesets: set[str] = set()
        for tgt_name, tgt_data in targets.items():
            if not isinstance(tgt_data, dict):
                continue
            if not _is_tb_target(tgt_name, tgt_data, self._tb_hints):
                continue
            fs_list = tgt_data.get("filesets") or []
            if isinstance(fs_list, list):
                for fs in fs_list:
                    if not isinstance(fs, str):
                        continue
                    # Skip RTL-only filesets even when included in a tb
                    # target — they're the DUT sources, not test sources.
                    if fs in _RTL_ONLY_FILESET_NAMES:
                        continue
                    tb_filesets.add(fs)
        if not tb_filesets:
            return []

        filesets = data.get("filesets") or {}
        if not isinstance(filesets, dict):
            return []

        out: List[BuildSystemLink] = []
        seen: set[tuple[str, str]] = set()
        for fs_name in tb_filesets:
            fs_data = filesets.get(fs_name)
            if not isinstance(fs_data, dict):
                continue
            files = fs_data.get("files") or []
            if not isinstance(files, list):
                continue
            for entry in files:
                # Each entry is either a bare path string or a {path: {opts}}
                # one-key dict.
                if isinstance(entry, str):
                    src = entry
                elif isinstance(entry, dict) and entry:
                    src = next(iter(entry.keys()))
                else:
                    continue
                key = (src, module)
                if key in seen:
                    continue
                seen.add(key)
                out.append(BuildSystemLink(
                    test_path=src,
                    module_name=module,
                    source_format=self.name,
                    source_file=str(core_path),
                    confidence_tier="high",
                    raw_match={"fileset": fs_name, "file": src,
                               "module": module},
                ))
        return out
