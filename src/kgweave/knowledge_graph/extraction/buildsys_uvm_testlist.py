# @summary
# UVM testlist .f file reader (Tier B Phase 3). Parses simulator-style
# .f files that mix +UVM_TESTNAME=foo entries with .sv testbench file
# paths and -f sub.f recursive includes. The testbench-filename
# heuristic (e.g. aes_tb.sv → 'aes') gives a medium-confidence
# test→module link. Recursion is depth-limited and cycle-safe.
# Exports: UvmTestlistReader
# Deps: pathlib, re, kgweave.knowledge_graph.common.sw_test_buildsys
# @end-summary
"""UVM testlist .f reader."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, List, Optional, Set

from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink

__all__ = ["UvmTestlistReader"]

_logger = logging.getLogger("rag.knowledge_graph.buildsys_uvm_testlist")

_UVM_TEST_RE = re.compile(r"\+UVM_TESTNAME=([A-Za-z_][\w]*)")
_F_INCLUDE_RE = re.compile(r"^\s*-f\s+(\S+)")
_DEFAULT_TB_SV_PATTERN = r"([A-Za-z_][\w]*)_tb\.sv"
_TB_SV_RE = re.compile(_DEFAULT_TB_SV_PATTERN + r"\b")
# Line-comment styles seen across simulators / wrappers:
#   - ``#`` (Make-style, also some sim wrappers)
#   - ``//`` (C/SV-style)
#   - ``--`` (Ada/VHDL-style — used by some lint front-ends)
_COMMENT_RE = re.compile(r"^\s*(#|//|--)")
_MAX_DEPTH = 4


class UvmTestlistReader:
    """Reader for SystemVerilog/UVM ``.f`` testlist files.

    The reader collects:
      - every ``+UVM_TESTNAME=<name>`` token (a UVM test class to run),
      - every ``*_tb.sv`` filename (the testbench, used to infer the
        module name via the well-known ``<module>_tb.sv`` convention).

    For each (test_name, module_name) pair, one ``BuildSystemLink`` is
    emitted with confidence_tier="medium" (the testbench-naming
    heuristic, while reliable in practice, is not authoritative).
    """

    name = "uvm_testlist"

    def __init__(
        self,
        glob: str = "**/*.f",
        testbench_filename_regex: Optional[str] = None,
        project_conventions: Optional[Any] = None,
    ) -> None:
        self._glob = glob
        if testbench_filename_regex is None and project_conventions is not None:
            pc = getattr(project_conventions, "uvm_testbench_filename_regex", None)
            if pc:
                testbench_filename_regex = pc
        pattern = testbench_filename_regex or _DEFAULT_TB_SV_PATTERN
        try:
            self._tb_sv_re = re.compile(pattern + r"\b" if not pattern.endswith(r"\b") else pattern)
        except re.error as exc:
            _logger.warning(
                "UvmTestlistReader: invalid testbench_filename_regex %r (%s); "
                "falling back to default", pattern, exc,
            )
            self._tb_sv_re = _TB_SV_RE

    def applies_to(self, project_root: Path) -> bool:
        try:
            return next(project_root.glob(self._glob), None) is not None
        except OSError:
            return False

    def read(self, project_root: Path) -> List[BuildSystemLink]:
        out: List[BuildSystemLink] = []
        for f_path in sorted(project_root.glob(self._glob)):
            visited: Set[Path] = set()
            uvm_tests, tb_modules = self._read_one(f_path, visited, depth=0)
            if not tb_modules:
                continue
            for test_name in sorted(uvm_tests):
                for module in sorted(tb_modules):
                    out.append(BuildSystemLink(
                        test_path=test_name,
                        module_name=module,
                        source_format=self.name,
                        source_file=str(f_path),
                        confidence_tier="medium",
                        raw_match={"uvm_testname": test_name,
                                   "tb_module": module},
                    ))
        return out

    def _read_one(
        self,
        f_path: Path,
        visited: Set[Path],
        depth: int,
    ) -> tuple[Set[str], Set[str]]:
        """Collect UVM test names + tb-derived module names. Recursive."""
        try:
            real = f_path.resolve()
        except OSError:
            return set(), set()
        if real in visited or depth >= _MAX_DEPTH:
            return set(), set()
        visited.add(real)
        try:
            text = f_path.read_text(errors="replace")
        except OSError:
            return set(), set()

        uvm_tests: Set[str] = set()
        tb_modules: Set[str] = set()

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or _COMMENT_RE.match(line):
                continue
            for m in _UVM_TEST_RE.finditer(line):
                uvm_tests.add(m.group(1))
            for m in self._tb_sv_re.finditer(line):
                tb_modules.add(m.group(1))
            inc = _F_INCLUDE_RE.match(line)
            if inc:
                sub = (f_path.parent / inc.group(1))
                if not sub.exists():
                    continue
                sub_tests, sub_mods = self._read_one(sub, visited, depth + 1)
                uvm_tests |= sub_tests
                tb_modules |= sub_mods

        return uvm_tests, tb_modules
