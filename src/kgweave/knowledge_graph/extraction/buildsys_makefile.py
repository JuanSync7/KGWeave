# @summary
# GNU Makefile reader (Tier B Phase 6). Heuristic-only — variable
# expansion is NOT performed and macros aren't traced. Recognized
# signals: MODULE/IP_NAME/IP_TOP variable assignment, test-<module>:
# / test_<module>: target rule names, and SRCS=<file>.c hints. Confidence
# tier: medium (easy to fool). `include sub.mk` directives are followed
# with depth-limited recursion.
# Exports: MakefileReader
# Deps: pathlib, kgweave.knowledge_graph.common.sw_test_buildsys
# @end-summary
"""GNU Makefile reader — structural (no regex)."""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any, List, Optional, Sequence, Set, Tuple

from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink

__all__ = ["MakefileReader"]

_logger = logging.getLogger("rag.knowledge_graph.buildsys_makefile")

_DEFAULT_MODULE_VARS = ["MODULE", "IP_NAME", "IP_TOP", "DUT", "DUT_NAME"]
_DEFAULT_TEST_TARGET_PREFIXES = ["test-", "test_"]
_DEFAULT_MODULE_STRIP_SUFFIXES = ["_top", "_dut", "_core", "_wrapper"]

# GNU Make assignment operators (in priority order for split detection).
_ASSIGN_OPS = [":=", "?=", "+=", "="]

_MAX_DEPTH = 4

# Extension set for SRCS recognition.
_SRC_EXTENSIONS = (".c", ".cc", ".cpp", ".sv")


def _is_identifier(s: str) -> bool:
    """Return True iff *s* matches ``[a-z][a-z0-9_]*`` (no regex)."""
    if not s:
        return False
    first = s[0]
    if first < "a" or first > "z":
        return False
    for ch in s[1:]:
        if not (("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "_"):
            return False
    return True


def _has_make_var_ref(val: str) -> bool:
    """Return True iff *val* contains an unexpanded make-variable reference."""
    # Structural: '$(' and '${' are GNU Make variable expansion delimiters — not source text patterns.
    return "$(" in val or "${" in val  # noqa: regex-ok


def _parse_assignment(line: str) -> Optional[Tuple[str, str]]:
    """Parse a GNU make assignment line into (variable_name, value).

    Supports all four operators: ``:=``, ``?=``, ``+=``, ``=``.
    Returns None if the line is not an assignment.
    """
    stripped = line.lstrip()
    # Try two-character operators first (avoids false-positive on bare ``=``).
    for op in (":=", "?=", "+="):
        if op in stripped:
            lhs, _, rhs = stripped.partition(op)
            lhs = lhs.strip()
            # Make sure the LHS is a simple identifier (A-Z, 0-9, _).
            if lhs and all(
                c.isalnum() or c == "_" for c in lhs
            ):
                return lhs, rhs.strip()
    # Bare ``=`` — only match if LHS is a clean identifier token.
    if "=" in stripped:
        lhs, _, rhs = stripped.partition("=")
        lhs = lhs.strip()
        if lhs and all(c.isalnum() or c == "_" for c in lhs) and " " not in lhs:
            return lhs, rhs.strip()
    return None


def _parse_include(line: str) -> Optional[str]:
    """Return the included path if *line* is an ``include`` or ``-include`` directive."""
    stripped = line.lstrip()
    if stripped.startswith("include ") or stripped.startswith("-include "):
        parts = stripped.split(None, 1)
        if len(parts) == 2:
            path = parts[1].strip()
            # Skip paths that are unexpanded make variable references.
            if _has_make_var_ref(path):
                return None
            return path
    return None


def _parse_target(line: str) -> Optional[str]:
    """Return the target name if *line* looks like ``TARGET:`` (a rule head).

    Ignores pattern rules (contain ``%``) and recipe lines (start with tab).
    """
    # Structural: tab is the GNU Make recipe-line prefix — a grammar token, not a pattern.
    if line.startswith("\t"):  # noqa: regex-ok
        return None
    # Structural: ':' is the Make rule-head separator token — not a source-text heuristic.
    if ":" in line:  # noqa: regex-ok
        target = line.split(":")[0].strip()
        # Skip empty targets, pattern rules, and phony-variable markers.
        if target and "%" not in target and "$" not in target:
            return target
    return None


class MakefileReader:
    """Heuristic Makefile reader (variable + target-name scrape) — no regex."""

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
        self._module_var_set: Set[str] = set(
            module_var_names if module_var_names else _DEFAULT_MODULE_VARS
        )

        # Resolve test_target_prefixes.
        if test_target_prefixes is None and project_conventions is not None:
            pc_pfx = getattr(project_conventions, "makefile_test_target_prefixes", None)
            if pc_pfx:
                test_target_prefixes = pc_pfx
        self._test_target_prefixes: List[str] = list(
            test_target_prefixes if test_target_prefixes else _DEFAULT_TEST_TARGET_PREFIXES
        )

        # Resolve module strip suffixes — store as frozenset of canonical forms.
        if module_strip_suffixes is None and project_conventions is not None:
            pc_sfx = getattr(project_conventions, "makefile_module_strip_suffixes", None)
            if pc_sfx:
                module_strip_suffixes = pc_sfx
        sfx_list = list(module_strip_suffixes) if module_strip_suffixes else list(
            _DEFAULT_MODULE_STRIP_SUFFIXES
        )
        # Normalise: ensure each suffix starts with ``_``.
        self._strip_suffixes: List[str] = [
            s if s.startswith("_") else f"_{s}" for s in sfx_list
        ]

    def _strip_module_suffix(self, val: str) -> str:
        """Remove a trailing module suffix if present."""
        for sfx in self._strip_suffixes:
            if val.endswith(sfx):
                return val[: -len(sfx)]
        return val

    def _extract_module_from_target(self, target: str) -> Optional[str]:
        """If *target* starts with a test prefix, return the module part."""
        for pfx in self._test_target_prefixes:
            if target.startswith(pfx):
                module = target[len(pfx):]
                if _is_identifier(module):
                    return module
        return None

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
            # Strip inline comments.
            line = raw.split("#", 1)[0]
            if not line.strip():
                continue

            # --- (1) Assignment line (MODULE := aes, SRCS = ..., etc.) ---
            parsed = _parse_assignment(line)
            if parsed is not None:
                var_name, val = parsed
                if var_name in self._module_var_set:
                    if _has_make_var_ref(val):
                        continue
                    cleaned = self._strip_module_suffix(val.strip())
                    if _is_identifier(cleaned):
                        modules.add(cleaned)
                    continue
                if var_name == "SRCS":
                    if _has_make_var_ref(val):
                        continue
                    for tok in val.split():
                        if tok.endswith(_SRC_EXTENSIONS):
                            srcs.add(tok)
                    continue

            # --- (2) Include directive ---
            inc_path_str = _parse_include(line)
            if inc_path_str is not None:
                inc_path = mf_path.parent / inc_path_str
                if inc_path.exists():
                    sub_mods, sub_srcs = self._collect(
                        inc_path, visited, depth + 1
                    )
                    modules |= sub_mods
                    srcs |= sub_srcs
                continue

            # --- (3) Target rule (test-aes:, test_aes:) ---
            target = _parse_target(line)
            if target is not None:
                mod = self._extract_module_from_target(target)
                if mod is not None:
                    modules.add(mod)
                continue

        return modules, srcs
