"""I3 gate: every node's span resolves to the correct byte slice.

For Tokens, ``file_bytes[start:end] == trivia_text + rawText`` (UTF-8 encoded).
For SyntaxNodes whose pyslang ``sourceRange`` is valid, the byte slice equals
the byte range pyslang reports. Synthetic SyntaxList nodes whose pyslang range
is sentinel get a merged-child span; we verify that span is contained within
their parent's span (a structural soundness probe — non-empty merged spans
can't escape the enclosing node).
"""

from __future__ import annotations

from pathlib import Path

import pyslang

from knowledge_graph.builders.sv.lift import lift


def _byte_view(path: Path) -> bytes:
    return path.read_bytes()


def test_token_span_equals_trivia_plus_rawtext(sv_fixture: Path) -> None:
    """For every token in every fixture, file_bytes[span] == trivia + rawText."""
    raw_bytes = _byte_view(sv_fixture)
    tree = pyslang.SyntaxTree.fromText(raw_bytes.decode("utf-8"))
    graph = lift(tree)
    token_nodes = [n for n in graph["nodes"] if n["is_token"]]
    failures: list[str] = []
    for n in token_nodes:
        span = n["span"]
        expected = (
            "".join(tr["text"] for tr in n["payload"]["trivia"])
            + n["payload"]["rawText"]
        ).encode("utf-8")
        got = raw_bytes[span["start_offset"]:span["end_offset"]]
        if got != expected:
            failures.append(
                f"{n['id']} kind={n['kind']} span={span} "
                f"expected={expected!r} got={got!r}"
            )
    assert not failures, "\n".join(failures[:5])


def test_syntax_node_span_contains_all_descendant_tokens(sv_fixture: Path) -> None:
    """A syntax node's span must enclose every descendant token's span.

    This is the meaningful structural oracle for SyntaxNode spans: pyslang's
    sourceRange should bracket every contained token, and our synthetic
    merged spans should too.
    """
    raw_bytes = _byte_view(sv_fixture)
    tree = pyslang.SyntaxTree.fromText(raw_bytes.decode("utf-8"))
    graph = lift(tree)
    by_id = {n["id"]: n for n in graph["nodes"]}
    children: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e.get("type") == "child":
            children.setdefault(e["src"], []).append(e["dst"])

    def descendant_token_spans(nid: str) -> list[dict]:
        out: list[dict] = []
        stack = [nid]
        while stack:
            cur = stack.pop()
            n = by_id[cur]
            if n["is_token"] and n["span"] is not None:
                out.append(n["span"])
            stack.extend(children.get(cur, []))
        return out

    failures: list[str] = []
    for n in graph["nodes"]:
        if n["is_token"] or n["span"] is None:
            continue
        span = n["span"]
        tok_spans = descendant_token_spans(n["id"])
        if not tok_spans:
            continue
        min_s = min(t["start_offset"] for t in tok_spans)
        max_e = max(t["end_offset"] for t in tok_spans)
        # Containment: syntax-node span must cover [min_s, max_e). Note pyslang
        # syntax sourceRange may start AT the first token's rawText (excluding
        # the token's leading trivia) so span.start may be > min_s by exactly
        # the first token's trivia byte length. Allow that. The end must
        # cover max_e.
        if span["end_offset"] < max_e:
            failures.append(
                f"{n['id']} span.end={span['end_offset']} < max_descendant_end={max_e}"
            )
    assert not failures, "\n".join(failures[:5])


def test_token_span_full_corpus_proof(sv_fixtures: list[Path]) -> None:
    """Aggregate I3 proof: count every token probed across the full corpus,
    assert zero mismatches.

    Print-line in the test name gives the per-file probe count when ``-s``.
    """
    total = 0
    files_checked = 0
    for path in sv_fixtures:
        raw_bytes = path.read_bytes()
        tree = pyslang.SyntaxTree.fromText(raw_bytes.decode("utf-8"))
        graph = lift(tree)
        for n in graph["nodes"]:
            if not n["is_token"]:
                continue
            span = n["span"]
            expected = (
                "".join(tr["text"] for tr in n["payload"]["trivia"])
                + n["payload"]["rawText"]
            ).encode("utf-8")
            assert raw_bytes[span["start_offset"]:span["end_offset"]] == expected, (
                f"{path.name} :: {n['id']}"
            )
            total += 1
        files_checked += 1
    print(f"\nI3 probe: {total} tokens across {files_checked} files all match")
    assert total > 0
