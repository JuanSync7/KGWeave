#!/usr/bin/env python3
"""Genericness scorer for KGWeave.

Counts behavior-controlling OpenTitan-specific references in src/kgweave/
that fall OUTSIDE permitted zones. Lower score = more generic.

Permitted zones (do not count):
  1. Inside ``ProjectConventions.opentitan()`` classmethod body
  2. Inside docstrings (triple-quoted strings)
  3. Inside ``#`` line comments
  4. Inside any line tagged with ``# noqa: ot-ref`` (explicit allowlist marker)

Outputs JSON to stdout:
  {"score": int, "hits": [{"file": str, "line": int, "text": str, "pattern": str}, ...]}

The correctness guard is intentionally NOT included here — run it separately
via scripts/genericness_guard.sh so a broken guard never silently masks the metric.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "kgweave"

# Behavior-controlling OT tokens — case-insensitive, word-boundary-anchored where useful.
PATTERNS = [
    re.compile(r"\bopentitan\b", re.IGNORECASE),
    re.compile(r"\blowrisc\b", re.IGNORECASE),
    re.compile(r"\bearlgrey\b", re.IGNORECASE),
    re.compile(r"\bdarjeeling\b", re.IGNORECASE),
    re.compile(r"hw/ip/"),
    re.compile(r"\btlul\b", re.IGNORECASE),
    re.compile(r"\bprim_lc\b"),
    re.compile(r"\bprim_mubi\b"),
    re.compile(r"\bottf\b", re.IGNORECASE),
    re.compile(r"\bdif_[a-z][a-z0-9_]*", re.IGNORECASE),
    re.compile(r"\baes_[a-z][a-z0-9_]*", re.IGNORECASE),
    re.compile(r"\bhmac_[a-z][a-z0-9_]*", re.IGNORECASE),
    re.compile(r"\bkmac_[a-z][a-z0-9_]*", re.IGNORECASE),
    re.compile(r"\botp_ctrl\b", re.IGNORECASE),
]

NOQA_MARKER = "noqa: ot-ref"


_OPENTITAN_FN_RE = re.compile(r"opentitan", re.IGNORECASE)


def opentitan_method_line_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """(start_line, end_line) of any function/method whose name contains ``opentitan``.

    Includes ``ProjectConventions.opentitan()`` and any ``_opentitan_defaults``-style
    private helpers that exist to feed it.
    """
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _OPENTITAN_FN_RE.search(node.name):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            ranges.append((start, end))
        # Module-level / class-level constants whose name contains "opentitan"
        # are explicitly OT-namespaced data — same category as opentitan() methods.
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and _OPENTITAN_FN_RE.search(tgt.id):
                    start = node.lineno
                    end = getattr(node, "end_lineno", start)
                    ranges.append((start, end))
                    break
        elif isinstance(node, ast.AnnAssign):
            tgt = node.target
            if isinstance(tgt, ast.Name) and _OPENTITAN_FN_RE.search(tgt.id):
                start = node.lineno
                end = getattr(node, "end_lineno", start)
                ranges.append((start, end))
    return ranges


def docstring_line_ranges(tree: ast.AST, source_lines: list[str]) -> set[int]:
    """Return line numbers (1-indexed) that fall inside any docstring or
    PEP-257 attribute docstring (a bare string Expr inside a class/module body).
    """
    inside: set[int] = set()

    # Module / class / function leading docstring
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                ds = body[0]
                start = ds.lineno
                end = getattr(ds, "end_lineno", start)
                for ln in range(start, end + 1):
                    inside.add(ln)

    # Bare-string Expr anywhere in a class/module body (attribute docstrings,
    # explanatory string literals between fields).
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef)):
            for child in getattr(node, "body", []):
                if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                    start = child.lineno
                    end = getattr(child, "end_lineno", start)
                    for ln in range(start, end + 1):
                        inside.add(ln)
    return inside


def is_comment_line(line: str) -> bool:
    return line.lstrip().startswith("#")


def scan_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        tree = None

    ot_ranges = opentitan_method_line_ranges(tree) if tree else []
    docstring_lines = docstring_line_ranges(tree, lines) if tree else set()

    def in_opentitan(ln: int) -> bool:
        return any(s <= ln <= e for s, e in ot_ranges)

    hits: list[dict] = []
    for i, line in enumerate(lines, start=1):
        if NOQA_MARKER in line:
            continue
        if in_opentitan(i):
            continue
        if i in docstring_lines:
            continue
        if is_comment_line(line):
            continue
        for pat in PATTERNS:
            m = pat.search(line)
            if m:
                hits.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": i,
                    "text": line.rstrip(),
                    "pattern": pat.pattern,
                    "match": m.group(0),
                })
                break  # one hit per line is enough for scoring
    return hits


def main() -> int:
    all_hits: list[dict] = []
    for py in sorted(SRC.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        all_hits.extend(scan_file(py))

    result = {"score": len(all_hits), "hits": all_hits}
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
