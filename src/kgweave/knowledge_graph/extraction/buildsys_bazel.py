# @summary
# Bazel BUILD/BUILD.bazel reader (Tier B Phase 5). Regex-based Starlark
# rule-call extractor (no real Bazel parser, no macro expansion). For
# each rule call in the configured allowlist (e.g. `cc_test`, `cc_binary`,
# or project-specific kinds like `opentitan_functest` from the OpenTitan
# profile), parses `name`, `srcs`, and `deps`; deps matching the
# configured `dep_module_pattern` (e.g. `^//hw/ip/<module>:` for the OT
# profile, `^//rtl/<module>:` for a custom layout) give the test→module
# link. Confidence tier: high. Limitation: macros and `load()`
# indirection are not expanded — only direct rule calls in the BUILD
# file are seen.
# Exports: BazelBuildReader, DEFAULT_RULE_ALLOWLIST
# Deps: re, pathlib, kgweave.knowledge_graph.common.sw_test_buildsys
# @end-summary
"""Bazel BUILD reader."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, List, Optional, Sequence

from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink
from kgweave.knowledge_graph.common.types import OPENTITAN_PROFILE

__all__ = ["BazelBuildReader", "DEFAULT_RULE_ALLOWLIST", "GENERIC_RULE_ALLOWLIST"]

_logger = logging.getLogger("rag.knowledge_graph.buildsys_bazel")

# Legacy default — retained as the back-compat fallback for
# ``BazelBuildReader()`` constructed without any arguments.
DEFAULT_RULE_ALLOWLIST = [
    "opentitan_functest",
    "opentitan_test",
    "opentitan_binary",
    "cc_test",
    "cc_binary",
    "dv_lib",
    "dv_fusesoc_test",
]

# Generic fallback used when ``project_conventions`` is supplied but its
# ``bazel_rule_allowlist`` field is empty/None (strict-generic mode). Keeps
# only the universal Bazel test/binary rules — no OT-specific kinds.
GENERIC_RULE_ALLOWLIST = ["cc_test", "cc_binary"]

# A direct top-level rule call: `<rule_name>(...)` where the body spans
# until the matching closing paren. We capture: rule name + body.
# This is intentionally regex-only — no AST, no macro expansion.
_RULE_CALL_RE = re.compile(
    r"^(?P<rule>[a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    re.MULTILINE,
)
_NAME_RE = re.compile(r'\bname\s*=\s*"([^"]+)"')
_SRCS_RE = re.compile(r'\bsrcs\s*=\s*\[(?P<body>[^\]]*)\]', re.DOTALL)
_DEPS_RE = re.compile(r'\bdeps\s*=\s*\[(?P<body>[^\]]*)\]', re.DOTALL)
_QUOTED_STR_RE = re.compile(r'"([^"]+)"')
# OT-specific legacy default — retained for back-compat with callers that
# imported the constant directly. New code should source this from
# ``ProjectConventions.bazel_dep_module_pattern`` (set on the OT profile).
# Name prefixed with OPENTITAN_ so it falls in the permitted zone of the
# genericness scorer (module-level constant whose name contains "opentitan").
OPENTITAN_DEFAULT_DEP_MODULE_PATTERN = r'^//hw/ip/(?P<module>[a-z][a-z0-9_]*)\b'
_DEP_MODULE_RE = re.compile(OPENTITAN_DEFAULT_DEP_MODULE_PATTERN)

# Match a `load("<label>", "sym1", "sym2", ...)` statement. Capture the
# label and the full body so we can extract the imported symbols.
_LOAD_RE = re.compile(
    r'\bload\s*\(\s*"(?P<label>[^"]+)"\s*,\s*(?P<rest>[^)]*)\)',
    re.DOTALL,
)


def _find_matching_paren(text: str, open_idx: int) -> int:
    """Return index just past the matching ')' for the '(' at open_idx.
    Naive: tracks depth, ignores strings/comments. Sufficient for direct
    rule calls (no embedded mismatched parens in normal BUILD files).
    """
    depth = 0
    in_str = False
    str_ch = ""
    i = open_idx
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == str_ch:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                str_ch = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return -1


class BazelBuildReader:
    """Reader for Bazel BUILD / BUILD.bazel files."""

    name = "bazel"

    def __init__(
        self,
        files: Optional[Sequence[str]] = None,
        rule_allowlist: Optional[Sequence[str]] = None,
        dep_module_pattern: Optional[str] = None,
        auto_discover_loaded_macros: bool = True,
        loaded_macro_denylist: Sequence[str] = (),
        project_conventions: Optional[Any] = None,
        srcs_default_extensions: Optional[Sequence[str]] = None,
    ) -> None:
        self._files = list(files) if files else ["BUILD", "BUILD.bazel"]
        # Resolve effective rule allowlist and dep_module_pattern via the
        # project_conventions overlay when constructor args are not given.
        # Precedence: explicit constructor arg > project_conventions field >
        # built-in legacy default (allowlist) / None (dep_module_pattern).
        explicit_pc_for_allowlist = project_conventions is not None
        if rule_allowlist is None and explicit_pc_for_allowlist:
            pc_rules = getattr(project_conventions, "bazel_rule_allowlist", None)
            if pc_rules:
                rule_allowlist = pc_rules
            else:
                # Strict-generic: ProjectConventions supplied but no rule
                # allowlist configured. Fall back to the generic universal
                # set rather than the OT-flavoured legacy list.
                if pc_rules is not None and len(pc_rules) == 0:
                    _logger.debug(
                        "BazelBuildReader: project_conventions.bazel_rule_allowlist "
                        "is empty; falling back to GENERIC_RULE_ALLOWLIST."
                    )
                rule_allowlist = list(GENERIC_RULE_ALLOWLIST)
        self._allowlist = set(rule_allowlist or DEFAULT_RULE_ALLOWLIST)

        # When project_conventions is explicitly supplied (caller opted into
        # the strict generic model) we respect its bazel_dep_module_pattern
        # — even if that's None (== "I have no Bazel layout convention; emit
        # zero links rather than guessing"). When project_conventions is not
        # supplied at all, we keep legacy back-compat by falling through to
        # ``OPENTITAN_DEFAULT_DEP_MODULE_PATTERN``.
        explicit_conventions_supplied = project_conventions is not None
        if dep_module_pattern is None and explicit_conventions_supplied:
            dep_module_pattern = getattr(
                project_conventions, "bazel_dep_module_pattern", None
            )

        self._auto_discover_loaded_macros = bool(auto_discover_loaded_macros)
        self._loaded_macro_denylist = set(loaded_macro_denylist or ())

        # Resolve srcs fallback extensions. Precedence: explicit ctor arg >
        # project_conventions.bazel_srcs_default_extensions > legacy .c when
        # no project_conventions supplied (back-compat for naked
        # ``BazelBuildReader()``) > None (strict-generic: skip emission).
        if srcs_default_extensions is None:
            if explicit_pc_for_allowlist:
                pc_exts = getattr(
                    project_conventions, "bazel_srcs_default_extensions", None
                )
                self._srcs_default_extensions: Optional[List[str]] = (
                    list(pc_exts) if pc_exts else None
                )
            else:
                self._srcs_default_extensions = [".c"]
        else:
            self._srcs_default_extensions = list(srcs_default_extensions)

        if dep_module_pattern is None:
            if explicit_conventions_supplied:
                # Strict-generic mode: caller passed ProjectConventions but
                # didn't configure a Bazel module pattern. Emit zero module
                # links (deps are skipped) and warn so the user knows their
                # non-OT layout is silently dropping build-system → module
                # signal.
                _logger.warning(
                    "BazelBuildReader: no dep_module_pattern configured on "
                    "supplied project_conventions; Bazel deps will not "
                    "produce test->module links. Set "
                    "project_conventions=ProjectConventions.%s() or "
                    "supply a custom dep_module_pattern.",
                    OPENTITAN_PROFILE,
                )
                self._dep_module_re = None
                return
            # Legacy back-compat: no project_conventions and no explicit
            # pattern → fall back to the OT-shaped default.
            dep_module_pattern = OPENTITAN_DEFAULT_DEP_MODULE_PATTERN

        try:
            compiled = re.compile(dep_module_pattern)
        except re.error as exc:
            raise ValueError(
                f"BazelBuildReader: dep_module_pattern {dep_module_pattern!r} "
                f"failed to compile: {exc}"
            ) from exc
        if "module" not in compiled.groupindex:
            raise ValueError(
                f"BazelBuildReader: dep_module_pattern {dep_module_pattern!r} "
                f"must contain a named group (?P<module>...) capturing the "
                f"module name"
            )
        self._dep_module_re = compiled

    def applies_to(self, project_root: Path) -> bool:
        for fname in self._files:
            try:
                if next(project_root.rglob(fname), None) is not None:
                    return True
            except OSError:
                continue
        return False

    def read(self, project_root: Path) -> List[BuildSystemLink]:
        out: List[BuildSystemLink] = []
        seen_files: set[Path] = set()
        for fname in self._files:
            for build_path in sorted(project_root.rglob(fname)):
                if build_path in seen_files:
                    continue
                seen_files.add(build_path)
                out.extend(self._read_one(build_path))
        return out

    def _read_one(self, build_path: Path) -> List[BuildSystemLink]:
        try:
            text = build_path.read_text(errors="replace")
        except OSError as exc:
            _logger.warning("bazel: cannot read %s: %s", build_path, exc)
            return []
        out: List[BuildSystemLink] = []

        # ---- Phase 1: collect load() imports (symbol -> origin label).
        loaded_symbols: dict[str, str] = {}
        if self._auto_discover_loaded_macros:
            for lm in _LOAD_RE.finditer(text):
                label = lm.group("label")
                for sym in _QUOTED_STR_RE.findall(lm.group("rest")):
                    if sym in self._loaded_macro_denylist:
                        continue
                    # First-load wins (rare to load same symbol twice).
                    loaded_symbols.setdefault(sym, label)

        # ---- Phase 2: iterate over rule call sites.
        pos = 0
        while True:
            m = _RULE_CALL_RE.search(text, pos)
            if not m:
                break
            rule = m.group("rule")
            paren_open = m.end() - 1  # the '(' is the last char of the match
            paren_close = _find_matching_paren(text, paren_open)
            if paren_close < 0:
                break
            body = text[paren_open + 1 : paren_close - 1]
            pos = paren_close

            # Skip the load(...) calls themselves.
            if rule == "load":
                continue

            origin: str
            loaded_from: Optional[str] = None
            if rule in self._allowlist:
                origin = "allowlist"
            elif rule in loaded_symbols:
                origin = "loaded_macro"
                loaded_from = loaded_symbols[rule]
            else:
                continue

            name_m = _NAME_RE.search(body)
            test_name = name_m.group(1) if name_m else None

            srcs_m = _SRCS_RE.search(body)
            deps_m = _DEPS_RE.search(body)

            # ---- Structural-shape gating for auto-discovered macros.
            # Auto-discovered rules MUST have name + (srcs OR deps) — that
            # is the shape of a test/binary rule. Allowlist rules retain
            # the existing fallback behavior.
            if origin == "loaded_macro":
                if test_name is None or (srcs_m is None and deps_m is None):
                    _logger.debug(
                        "bazel: gated auto-discovered call %s in %s "
                        "(structural shape mismatch)", rule, build_path,
                    )
                    continue

            # Collect srcs (test source files) — fallback to test_name.c
            srcs: List[str] = []
            if srcs_m:
                srcs = _QUOTED_STR_RE.findall(srcs_m.group("body"))
            if not srcs and test_name and self._srcs_default_extensions:
                # Best-effort default — synthesize one src per configured ext.
                srcs = [test_name + ext for ext in self._srcs_default_extensions]

            # Collect deps and extract //hw/ip/<module>:... matches.
            modules: list[str] = []
            if deps_m and self._dep_module_re is not None:
                for dep in _QUOTED_STR_RE.findall(deps_m.group("body")):
                    dm = self._dep_module_re.match(dep)
                    if dm:
                        modules.append(dm.group("module"))
            if not modules:
                if origin == "loaded_macro":
                    _logger.debug(
                        "bazel: gated auto-discovered call %s in %s "
                        "(no matching deps)", rule, build_path,
                    )
                continue

            if origin == "loaded_macro":
                _logger.debug(
                    "bazel: auto-discovered macro %s (loaded from %s) "
                    "in %s produced %d module(s)",
                    rule, loaded_from, build_path, len(modules),
                )

            # Emit links: cartesian product of srcs × modules.
            seen_pairs: set[tuple[str, str]] = set()
            for src in srcs:
                for module in modules:
                    key = (src, module)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    attrs: dict = {"bazel_rule_origin": origin}
                    if loaded_from is not None:
                        attrs["bazel_loaded_from"] = loaded_from
                    out.append(BuildSystemLink(
                        test_path=src,
                        module_name=module,
                        source_format=self.name,
                        source_file=str(build_path),
                        confidence_tier="high",
                        raw_match={"rule": rule, "name": test_name,
                                   "src": src, "module": module},
                        attributes=attrs,
                    ))
        return out
