#!/usr/bin/env python3
"""Regex/fragile-string fragility scorer for KGWeave extractors.

Counts patterns that are likely to break on arbitrary SystemVerilog (or other
source-code) input under ``src/kgweave/knowledge_graph/extraction/``. Lower
score = more robust (parser-driven, structural).

What counts (one hit per AST node):

  1. ``re.<func>(...)`` — compile, search, match, fullmatch, findall, finditer,
     sub, subn, split.  Each call is a hit.
  2. Substring/prefix/suffix checks against literal strings whose receiver
     variable name suggests it holds **source-code text** rather than an
     AST-node kind name or a filesystem path.  Specifically:
       - ``x.startswith("...")``, ``x.endswith("...")``  (literal arg)
       - ``"literal" in x``  (literal on the left of an ``in``)
     where the receiver ``x`` matches one of:
       ``line, text, content, src, source, body, raw, code, snippet, chunk,
        token, value, val, s, expr, stmt, signal, name`` (case-insensitive
       substring match).

What is NOT counted (assumed robust):

  - Receivers whose name contains ``kind``, ``tag``, ``type``, ``node``, or
    ``rule`` — these are AST/tree-sitter node-type checks, robust by design.
  - Receivers whose name contains ``path``, ``file``, ``ext``, ``suffix`` —
    filesystem paths, not source content.
  - Pre-compiled-pattern method calls (e.g. ``_RE.search(x)``) — already
    counted at the ``re.compile`` site; counting both double-counts.

Permitted zones (do not count):

  - Any line containing the marker ``# noqa: regex-ok`` (with a one-line
    rationale).
  - ``__init__.py`` files (re-export shells).

Outputs JSON to stdout:
  {"score": int, "by_kind": {...}, "hits": [{file, line, kind, snippet}]}

The correctness guard runs separately via ``scripts/regex_fragility_guard.sh``.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "src" / "kgweave" / "knowledge_graph" / "extraction"

RE_FUNCS = {
    "compile", "search", "match", "fullmatch",
    "findall", "finditer", "sub", "subn", "split",
}
NOQA = "noqa: regex-ok"

# Receiver-name heuristics for substring/in checks. Lowercased substring match.
SAFE_RECEIVER_TOKENS = (
    "kind", "tag", "type", "node", "rule",     # AST / tree-sitter node descriptors
    "path", "file", "ext", "suffix",           # filesystem paths
)
CONTENT_RECEIVER_TOKENS = (
    "line", "text", "content", "src", "source", "body",
    "raw", "code", "snippet", "chunk", "token",
    "value", "val", "expr", "stmt", "signal", "name",
)


def _receiver_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_content_receiver(node: ast.AST) -> bool:
    name = _receiver_name(node)
    if name is None:
        return False
    lower = name.lower()
    if any(tok in lower for tok in SAFE_RECEIVER_TOKENS):
        return False
    return any(tok in lower for tok in CONTENT_RECEIVER_TOKENS)


def _is_str_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_str_tuple(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Tuple)
        and bool(node.elts)
        and all(_is_str_constant(e) for e in node.elts)
    )


def scan_file(path: Path, allowed_lines: set[int]) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    hits: list[dict] = []
    src_lines = text.splitlines()

    def add(node: ast.AST, kind: str) -> None:
        ln = getattr(node, "lineno", 0)
        if ln in allowed_lines:
            return
        snippet = src_lines[ln - 1].strip() if 0 < ln <= len(src_lines) else ""
        hits.append({
            "file": str(path.relative_to(ROOT)),
            "line": ln,
            "kind": kind,
            "snippet": snippet[:200],
        })

    for node in ast.walk(tree):
        # 1. re.<func>(...) — module-level regex use, plus aliased ``import re as _re``.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            recv = node.func.value
            if (
                isinstance(recv, ast.Name)
                and recv.id in {"re", "_re"}
                and attr in RE_FUNCS
            ):
                add(node, "re_module_call")
                continue
            # 2. content-receiver .startswith / .endswith with literal-string arg(s)
            if attr in {"startswith", "endswith"} and node.args:
                a0 = node.args[0]
                if (_is_str_constant(a0) or _is_str_tuple(a0)) and _is_content_receiver(recv):
                    add(node, f"str_{attr}_literal")
                    continue

        # 3. "literal" in <content_receiver>
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.In):
            if _is_str_constant(node.left) and _is_content_receiver(node.comparators[0]):
                add(node, "in_literal_substring")
                continue

    return hits


def collect_noqa_lines(path: Path) -> set[int]:
    out: set[int] = set()
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if NOQA in line:
            out.add(i)
    return out


def main() -> int:
    all_hits: list[dict] = []
    for py in sorted(TARGET.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        if py.name == "__init__.py":
            continue
        allowed = collect_noqa_lines(py)
        all_hits.extend(scan_file(py, allowed))

    by_kind: dict[str, int] = {}
    for h in all_hits:
        by_kind[h["kind"]] = by_kind.get(h["kind"], 0) + 1

    result = {
        "score": len(all_hits),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "hits": all_hits,
    }
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
