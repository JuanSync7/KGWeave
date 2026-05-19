"""Hand-rolled byte-offset markdown scanner.

Produces a flat list of :class:`MdNode` instances covering exactly four
token kinds, each with a precise byte span (matching the I3 round-trip
contract):

* ``MdDocument``  — covers the entire file (offsets 0..len).
* ``MdHeading``   — ATX (``# foo``, ``## foo``, ...) one-line headings.
* ``MdCodeFence`` — fenced code blocks (``` or ~~~), span covers the
                    entire block including the fences.
* ``MdInlineCode``— backtick-delimited inline code spans inside non-fence
                    regions.

Why hand-rolled and not mistune: mistune 3.x tokens carry no source
offsets. Reconciling its AST with raw text would mean re-scanning anyway;
the scanner here is small enough that the dependency would add no value
beyond what's already in :mod:`re` and string slicing. We *do* import
mistune at the top so the dependency stays declared — if someone wants
richer lift later (links, images) mistune is the obvious next step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# Top-level dependency declaration: mistune is the path-of-least-resistance
# extension point for adding more node kinds. The scanner below uses it
# only as a feature flag — when False, callers know mistune itself is
# unavailable and richer parses won't be added.
try:  # pragma: no cover - smoke import
    import mistune  # noqa: F401

    MISTUNE_AVAILABLE = True
except ImportError:  # pragma: no cover
    MISTUNE_AVAILABLE = False


# ATX heading: 1-6 #, then required space (CommonMark), then text.
# Optional trailing ## stripped at render-time, but we keep the whole
# line for the span (lossless).
_ATX_RE = re.compile(rb"^(?P<hashes>#{1,6})[ \t](?P<text>.*?)\s*#*\s*$")
# Fenced code block opener: optional indent (0-3 spaces), then ``` or ~~~.
_FENCE_OPEN_RE = re.compile(
    rb"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$"
)


@dataclass(frozen=True)
class MdNode:
    """Lifted markdown token with byte-precise span.

    ``start``/``end`` are inclusive/exclusive byte offsets into the file
    content. ``text`` is the *content* (heading text or code body or
    inline-code body) — useful for downstream connectors that match on
    the literal token.
    """

    kind: str
    start: int
    end: int
    text: str
    parent_idx: int | None = None
    payload: dict[str, object] = field(default_factory=dict)


def _line_col_for(content: bytes, offset: int) -> tuple[int, int]:
    """1-based line and 0-based column for ``offset`` in ``content``."""
    if offset <= 0:
        return 1, 0
    prefix = content[:offset]
    line = prefix.count(b"\n") + 1
    last_nl = prefix.rfind(b"\n")
    col = offset - last_nl - 1 if last_nl >= 0 else offset
    return line, col


def lift_markdown(content: bytes) -> list[MdNode]:
    """Lift ``content`` into MdNodes.

    The document node is index 0 and parents every other node. Headings
    and code fences are direct children of the document; inline-code
    spans are children of whatever heading/paragraph contains them. For
    v1 we don't materialize the paragraph itself — inline-code nodes
    point directly at the document. That keeps the node count small and
    the connector logic trivial (no need to walk through paragraphs).
    """
    nodes: list[MdNode] = []
    nodes.append(MdNode(kind="MdDocument", start=0, end=len(content), text=""))
    doc_idx = 0

    # First pass: find every line boundary, line ranges.
    line_starts: list[int] = [0]
    for i, b in enumerate(content):
        if b == 0x0A:  # \n
            line_starts.append(i + 1)
    # Sentinel: pretend a final line start after the file end.
    line_starts.append(len(content) + 1)

    def line_end(line_idx: int) -> int:
        # Offset of the trailing newline (exclusive end of line content).
        next_start = line_starts[line_idx + 1] - 1
        # Clamp to content length for the final partial line.
        return min(next_start, len(content))

    in_fence = False
    fence_marker: bytes = b""
    fence_start_offset = 0
    inline_skip_lines: set[int] = set()  # lines covered by fences

    n_lines = len(line_starts) - 1
    li = 0
    while li < n_lines:
        ls = line_starts[li]
        le = line_end(li)
        raw = content[ls:le]

        if in_fence:
            inline_skip_lines.add(li)
            stripped = raw.lstrip(b" ")
            if stripped.startswith(fence_marker) and set(
                stripped.rstrip()
            ) == {fence_marker[0:1][0]}:
                # Fence close. End offset = end of this line including \n
                # if present.
                end_offset = line_starts[li + 1] - 1 + 1  # include \n
                end_offset = min(end_offset, len(content))
                # Include trailing \n if present.
                if end_offset < len(content) and content[end_offset - 1] != 0x0A:
                    pass
                # Simpler: end at the line's full extent including newline.
                end_offset = (
                    line_starts[li + 1]
                    if li + 1 < len(line_starts) - 1
                    else le + (1 if le < len(content) and content[le] == 0x0A else 0)
                )
                end_offset = min(end_offset, len(content))
                body_start = fence_start_offset
                nodes.append(
                    MdNode(
                        kind="MdCodeFence",
                        start=body_start,
                        end=end_offset,
                        text=content[body_start:end_offset].decode(
                            "utf-8", errors="replace"
                        ),
                        parent_idx=doc_idx,
                        payload={"fence": fence_marker.decode("ascii")},
                    )
                )
                in_fence = False
                fence_marker = b""
            li += 1
            continue

        # Fence open?
        m = _FENCE_OPEN_RE.match(raw)
        if m:
            in_fence = True
            fence_marker = m.group("fence")
            fence_start_offset = ls
            inline_skip_lines.add(li)
            li += 1
            continue

        # ATX heading?
        h = _ATX_RE.match(raw)
        if h:
            level = len(h.group("hashes"))
            text = h.group("text").decode("utf-8", errors="replace")
            # Heading span: the entire line (no trailing newline — keeps
            # consecutive heading spans non-overlapping).
            nodes.append(
                MdNode(
                    kind="MdHeading",
                    start=ls,
                    end=le,
                    text=text,
                    parent_idx=doc_idx,
                    payload={"level": level},
                )
            )
            li += 1
            continue

        li += 1

    # Second pass: scan for inline backtick code outside fence regions.
    # We re-walk lines because inline-code can also appear inside heading
    # lines; ATX headings are single lines so we treat any non-fence line
    # the same way.
    pos = 0
    while pos < len(content):
        b = content[pos]
        if b != 0x60:  # backtick
            pos += 1
            continue
        # Skip if inside a fence region.
        cur_line = content[:pos].count(b"\n")
        if cur_line in inline_skip_lines:
            pos += 1
            continue
        # Count opening backtick run.
        run_start = pos
        while pos < len(content) and content[pos] == 0x60:
            pos += 1
        run_len = pos - run_start
        # Look for a matching run of identical length (CommonMark rule).
        scan = pos
        found_close = -1
        while scan < len(content):
            if content[scan] == 0x60:
                close_start = scan
                while scan < len(content) and content[scan] == 0x60:
                    scan += 1
                if scan - close_start == run_len:
                    found_close = close_start
                    break
            else:
                if content[scan] == 0x0A:
                    # An inline-code span MUST stay on a single line for
                    # our minimalist v1 — bail if we cross a newline
                    # without closing.
                    break
                scan += 1
        if found_close < 0:
            # Unclosed: skip the opening run entirely.
            continue
        body_start = run_start + run_len
        body_end = found_close
        full_end = found_close + run_len
        text = content[body_start:body_end].decode("utf-8", errors="replace")
        nodes.append(
            MdNode(
                kind="MdInlineCode",
                start=run_start,
                end=full_end,
                text=text,
                parent_idx=doc_idx,
                payload={"backticks": run_len},
            )
        )
        pos = full_end

    return nodes


__all__ = ["MdNode", "lift_markdown", "MISTUNE_AVAILABLE"]
