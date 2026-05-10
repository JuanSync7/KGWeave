"""Test that every re.<func> call in regex_extractor.py carries a # noqa: regex-ok marker.

TDD: this test was written BEFORE the markers were added, so it initially fails.
After iter-016 adds the markers it must pass — verifying the documentation
contract is enforced at the source level.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REGEX_EXTRACTOR = (
    ROOT / "src" / "kgweave" / "knowledge_graph" / "extraction" / "regex_extractor.py"
)

RE_FUNCS = {
    "compile", "search", "match", "fullmatch",
    "findall", "finditer", "sub", "subn", "split",
}
NOQA_MARKER = "noqa: regex-ok"


def _collect_re_call_lines(path: Path) -> list[int]:
    """Return line numbers of every re.<func>(...) call in *path*."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            recv = node.func.value
            if (
                isinstance(recv, ast.Name)
                and recv.id in {"re", "_re"}
                and attr in RE_FUNCS
            ):
                lines.append(node.lineno)
    return lines


def test_all_re_calls_have_noqa_marker() -> None:
    """Every re.<func> call line must carry '# noqa: regex-ok'."""
    source_lines = REGEX_EXTRACTOR.read_text(encoding="utf-8").splitlines()
    re_call_lines = _collect_re_call_lines(REGEX_EXTRACTOR)

    assert re_call_lines, "Expected at least one re.<func> call in regex_extractor.py"

    missing: list[tuple[int, str]] = []
    for lineno in re_call_lines:
        line_text = source_lines[lineno - 1]
        if NOQA_MARKER not in line_text:
            missing.append((lineno, line_text.strip()))

    assert not missing, (
        f"The following re.<func> calls in regex_extractor.py are missing "
        f"'# noqa: regex-ok' markers:\n"
        + "\n".join(f"  line {ln}: {snip}" for ln, snip in missing)
    )


def test_noqa_markers_have_preceding_rationale() -> None:
    """Every noqa marker line must have a rationale comment on the preceding line."""
    source_lines = REGEX_EXTRACTOR.read_text(encoding="utf-8").splitlines()
    re_call_lines = set(_collect_re_call_lines(REGEX_EXTRACTOR))

    missing_rationale: list[tuple[int, str]] = []
    for lineno in re_call_lines:
        line_text = source_lines[lineno - 1]
        if NOQA_MARKER not in line_text:
            continue  # marker absence is caught by test_all_re_calls_have_noqa_marker
        # Check the preceding non-empty line is a rationale comment
        prev_lineno = lineno - 1
        # Walk back past blank lines
        while prev_lineno > 0 and source_lines[prev_lineno - 1].strip() == "":
            prev_lineno -= 1
        if prev_lineno < 1:
            missing_rationale.append((lineno, line_text.strip()))
            continue
        prev_line = source_lines[prev_lineno - 1].strip()
        # Accept: inline rationale on the noqa line itself (after the marker)
        # OR a comment-only line above that mentions "regex-ok" or "#"
        if not prev_line.startswith("#"):
            missing_rationale.append((lineno, line_text.strip()))

    assert not missing_rationale, (
        f"The following noqa-marked regex lines lack a preceding rationale comment:\n"
        + "\n".join(f"  line {ln}: {snip}" for ln, snip in missing_rationale)
    )
