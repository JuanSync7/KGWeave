# @summary
# GNU Makefile reader (Tier B Phase 6). Heuristic-only — variable
# expansion is NOT performed and macros aren't traced. Recognized
# signals: MODULE/IP_NAME/IP_TOP variable assignments, test-<module>:
# / test_<module>: target rule names, and SRCS=<file>.c hints. Confidence
# tier: medium (easy to fool). `include sub.mk` directives are followed
# with depth-limited recursion.
# Exports: MakefileReader
# Deps: re, pathlib, kgweave.knowledge_graph.common.sw_test_buildsys
# @end-summary
"""GNU Makefile reader."""

from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import Path
from typing import Any, List, Optional, Sequence, Set, Tuple

from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink

__all__ = ["MakefileReader"]

_logger = logging.getLogger("rag.knowledge_graph.buildsys_makefile")

_DEFAULT_MODULE_VARS = ["MODULE", "IP_NAME", "IP_TOP", "DUT", "DUT_NAME"]
_DEFAULT_TEST_TARGET_PREFIXES = ["test-", "test_"]
_DEFAULT_MODULE_STRIP_SUFFIXES = ["_top", "_dut", "_core", "_wrapper"]

_SRCS_RE = re.compile(r"^\s*SRCS\s*[:?+]?=\s*(?P<val>.+?)\s*$")
_INCLUDE_RE = re.compile(r"^\s*-?include\s+(\S+)")
_MAKE_VAR_REF_RE = re.compile(r"\$[\(\{]")
_MAX_DEPTH = 4


class MakefileReader:
    """Heuristic Makefile reader (variable + target-name scrape)."""

    name = "makefile"

    def __init__(
        self,
        files: Optional[Sequence[str]] = None,
        module_var_names: Optional[Sequence[str]] = None,
        test_target_prefixes: Optional[Sequence[str]] = None,
        module_strip_suffixes: Optional[Sequence[str]] = None,
        project_conventions: Optional[Any] = None,
    ) -> None:
        self._files = list(files) if files else ["Makefile", "makefile", "*.mk"]

        # Resolve module_var_names. Precedence: explicit > project_conventions > default.
        if module_var_names is None and project_conventions is not None:
            pc_vars = getattr(project_conventions, "makefile_module_vars", None)
            if pc_vars:
                module_var_names = pc_vars
        var_list = list(module_var_names) if module_var_names else list(_DEFAULT_MODULE_VARS)
        var_alt = "|".join(re.escape(v) for v in var_list)
        self._var_re = re.compile(
            rf"^\s*(?P<var>{var_alt})\s*[:?+]?=\s*(?P<val>.+?)\s*$"
        )

        # Resolve test_target_prefixes.
        if test_target_prefixes is None and project_conventions is not None:
            pc_pfx = getattr(project_conventions, "makefile_test_target_prefixes", None)
            if pc_pfx:
                test_target_prefixes = pc_pfx
        pfx_list = list(test_target_prefixes) if test_target_prefixes else list(
            _DEFAULT_TEST_TARGET_PREFIXES
        )
        pfx_alt = "|".join(re.escape(p) for p in pfx_list)
        # Each prefix is followed by an identifier name (the module).
        self._test_target_re = re.compile(
            rf"^(?P<target>(?:{pfx_alt})(?P<module>[a-z][a-z0-9_]*))\s*:"
        )

        # Resolve module strip suffixes.
        if module_strip_suffixes is None and project_conventions is not None:
            pc_sfx = getattr(project_conventions, "makefile_module_strip_suffixes", None)
            if pc_sfx:
                module_strip_suffixes = pc_sfx
        sfx_list = list(module_strip_suffixes) if module_strip_suffixes else list(
            _DEFAULT_MODULE_STRIP_SUFFIXES
        )
        if sfx_list:
            # Suffixes may include leading underscore or not; preserve as-is.
            sfx_alt = "|".join(re.escape(s.lstrip("_")) for s in sfx_list)
            self._module_strip_re = re.compile(rf"_(?:{sfx_alt})$")
        else:
            self._module_strip_re = None

    def _candidate_files(self, project_root: Path) -> List[Path]:
        out: List[Path] = []
        seen: Set[Path] = set()
        for pat in self._files:
            try:
                for p in sorted(project_root.rglob(pat)):
                    if p.is_file() and p not in seen:
                        seen.add(p)
                        out.append(p)
            except OSError:
                continue
        return out

    def applies_to(self, project_root: Path) -> bool:
        return bool(self._candidate_files(project_root))

    def read(self, project_root: Path) -> List[BuildSystemLink]:
        out: List[BuildSystemLink] = []
        for mf_path in self._candidate_files(project_root):
            out.extend(self._read_one(mf_path))
        return out

    def _read_one(self, mf_path: Path) -> List[BuildSystemLink]:
        visited: Set[Path] = set()
        modules, srcs = self._collect(mf_path, visited, depth=0)
        if not modules:
            return []
        if not srcs:
            srcs = {mf_path.name}  # fallback so we still emit a link
        out: List[BuildSystemLink] = []
        for module in sorted(modules):
            for src in sorted(srcs):
                out.append(BuildSystemLink(
                    test_path=src,
                    module_name=module,
                    source_format=self.name,
                    source_file=str(mf_path),
                    confidence_tier="medium",
                    raw_match={"module": module, "src": src},
                ))
        return out

    def _collect(
        self,
        mf_path: Path,
        visited: Set[Path],
        depth: int,
    ) -> Tuple[Set[str], Set[str]]:
        try:
            real = mf_path.resolve()
        except OSError:
            return set(), set()
        if real in visited or depth >= _MAX_DEPTH:
            return set(), set()
        visited.add(real)
        try:
            text = mf_path.read_text(errors="replace")
        except OSError:
            return set(), set()
        modules: Set[str] = set()
        srcs: Set[str] = set()
        for raw in text.splitlines():
            line = raw.split("#", 1)[0]
            if not line.strip():
                continue
            mv = self._var_re.match(line)
            if mv:
                val = mv.group("val").strip()
                # Skip values that contain make var references (unexpanded).
                if _MAKE_VAR_REF_RE.search(val):
                    continue
                # Strip well-known suffixes (aes_top → aes, aes_dut → aes).
                if self._module_strip_re is not None:
                    cleaned = self._module_strip_re.sub("", val)
                else:
                    cleaned = val
                if re.match(r"^[a-z][a-z0-9_]*$", cleaned):
                    modules.add(cleaned)
                continue
            ms = _SRCS_RE.match(line)
            if ms:
                val = ms.group("val").strip()
                if _MAKE_VAR_REF_RE.search(val):
                    continue
                for tok in val.split():
                    if tok.endswith((".c", ".cc", ".cpp", ".sv")):
                        srcs.add(tok)
                continue
            mt = self._test_target_re.match(line)
            if mt:
                modules.add(mt.group("module"))
                continue
            mi = _INCLUDE_RE.match(line)
            if mi:
                inc_path = mf_path.parent / mi.group(1)
                if inc_path.exists():
                    sub_mods, sub_srcs = self._collect(
                        inc_path, visited, depth + 1
                    )
                    modules |= sub_mods
                    srcs |= sub_srcs
        return modules, srcs
