# @summary
# UVM testlist .f file reader (Tier B Phase 3). Parses simulator-style
# .f files that mix +UVM_TESTNAME=foo entries with .sv testbench file
# paths and -f sub.f recursive includes. The testbench-filename
# heuristic (e.g. aes_tb.sv → 'aes') gives a medium-confidence
# test→module link. Recursion is depth-limited and cycle-safe.
# Exports: UvmTestlistReader
# Deps: pathlib, kgweave.knowledge_graph.common.sw_test_buildsys
# @end-summary
"""UVM testlist .f reader — structural parsing only, no regex."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink

__all__ = ["UvmTestlistReader"]

_logger = logging.getLogger("rag.knowledge_graph.buildsys_uvm_testlist")

# Comment prefixes recognised across simulator / wrapper flavours:
#   - ``#``   (Make-style, also some sim wrappers)
#   - ``//``  (C/SV-style)
#   - ``--``  (Ada/VHDL-style — used by some lint front-ends)
_COMMENT_PREFIXES: Tuple[str, ...] = ("#", "//", "--")

# Token prefix that identifies a UVM test-name plusarg.
_UVM_TESTNAME_PREFIX = "+UVM_TESTNAME="

# Default testbench filename suffix: <module>_tb.sv
_DEFAULT_TB_SUFFIX = "_tb.sv"

_MAX_DEPTH = 4


def _is_comment(line: str) -> bool:
    """Return True if *line* (already stripped) starts with a comment marker."""
    return line.startswith(_COMMENT_PREFIXES)


def _extract_uvm_testnames(line: str) -> List[str]:
    """Extract every ``+UVM_TESTNAME=<name>`` value from *line*.

    Tokens are split on whitespace so that a line like::

        +UVM_VERBOSITY=HIGH +UVM_TESTNAME=foo +UVM_NO_RELNOTES=1

    yields only ``["foo"]``.
    """
    names = []
    for token in line.split():
        if token.startswith(_UVM_TESTNAME_PREFIX):
            name = token[len(_UVM_TESTNAME_PREFIX):]
            if name:
                names.append(name)
    return names


def _extract_f_include(line: str) -> Optional[str]:
    """Return the filename following a ``-f`` token, or None.

    Handles::

        -f sub.f
        -f  sub/dir/file.f   (extra whitespace)
    """
    tokens = line.split()
    if len(tokens) >= 2 and tokens[0] == "-f":
        return tokens[1]
    return None


def _extract_tb_module(line: str, tb_suffix: str) -> Optional[str]:
    """Return the module name encoded in a ``<module><tb_suffix>`` filename on
    *line*, or None.

    Each whitespace-separated token is checked: if the *basename* of the
    token (the part after the last ``/``) ends with *tb_suffix*, the part
    before the suffix is returned as the module name.

    Examples with suffix ``_tb.sv``::

        ``${PROJ}/hw/ip/aes/dv/aes_tb.sv``  → ``"aes"``
        ``aes_tb.sv``                         → ``"aes"``
    """
    for token in line.split():
        basename = token.rsplit("/", 1)[-1]
        if basename.endswith(tb_suffix):
            module = basename[: -len(tb_suffix)]
            if module:
                return module
    return None


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
        testbench_filename_suffix: Optional[str] = None,
        project_conventions: Optional[Any] = None,
    ) -> None:
        self._glob = glob
        suffix = testbench_filename_suffix
        if suffix is None and project_conventions is not None:
            pc_suffix = getattr(project_conventions, "uvm_testbench_filename_suffix", None)
            if pc_suffix:
                suffix = pc_suffix
        self._tb_suffix: str = suffix or _DEFAULT_TB_SUFFIX

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
            if not line or _is_comment(line):
                continue

            for name in _extract_uvm_testnames(line):
                uvm_tests.add(name)

            module = _extract_tb_module(line, self._tb_suffix)
            if module:
                tb_modules.add(module)

            inc_path = _extract_f_include(line)
            if inc_path:
                sub = f_path.parent / inc_path
                if not sub.exists():
                    continue
                sub_tests, sub_mods = self._read_one(sub, visited, depth + 1)
                uvm_tests |= sub_tests
                tb_modules |= sub_mods

        return uvm_tests, tb_modules
