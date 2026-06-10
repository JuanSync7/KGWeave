"""Cypher A/B runner.

Two modes::

    # Validate the Cypher surface's oracles (ceiling) — no model, no API key:
    uv run python -m research.ast_experiment.evals.cypher_ab.run_ab

    # Grade a blind panel file:
    uv run python -m research.ast_experiment.evals.cypher_ab.run_ab \
        --surface cypher --replay blind_runs/cypher_opus.json

A blind file is a JSON list of ``{"id": "Q1", "answer": <...>}`` where
``answer`` is a Cypher string. Each answer is executed against the graph and
set-compared to independent truth.

The legacy pattern-dict (``graph_query``) arm was removed in S7 — the retired
DSL is no longer a measurable surface, so only the Cypher ceiling is reported.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from research.ast_experiment.src.build import build_kg
from .questions import QUESTIONS
from .kuzu_load import load_kuzu, run_cypher

_ROOT = Path(__file__).resolve().parents[2]
CORPUS = sorted((_ROOT / "corpus").glob("*.sv"))


def _ok(answer: frozenset[str], acc: list[frozenset[str]]) -> bool:
    """Pass if the answer equals ANY acceptable projection (name or path) — the
    name-vs-path convention is a separate, orthogonal lever, neutralised here."""
    return any(answer == t for t in acc)


def validate_oracles(graph, conn) -> int:
    print(f"\n{'='*78}\n  Surface-ceiling validation (oracles)\n{'='*78}")
    print(f"  {'Q':<22}{'AXIS':<34}{'cypher':<8}")
    print(f"  {'-'*66}")
    rc = 0
    for q in QUESTIONS:
        acc = q.acceptable(graph)
        if q.cypher_oracle is None:
            cy = "gap"
        else:
            try:
                cy = "PASS" if _ok(run_cypher(conn, q.cypher_oracle), acc) else "FAIL"
            except Exception:  # noqa: BLE001
                cy = "ERR"
        if cy in ("FAIL", "ERR"):
            rc = 1
        print(f"  {q.id:<22}{q.axis:<34}{cy:<8}")
    print(f"  {'-'*66}")
    cgap = [q.id for q in QUESTIONS if q.cypher_oracle is None]
    print(f"  cypher ceiling: {len(QUESTIONS)-len(cgap)}/{len(QUESTIONS)}  (gaps: {cgap})")
    print(f"{'='*78}\n")
    return rc


def grade_replay(graph, conn, surface: str, path: str) -> None:
    data = {d["id"]: d["answer"] for d in json.loads(Path(path).read_text())}
    print(f"\n  Blind grade — surface={surface}  file={Path(path).name}")
    print(f"  {'-'*70}")
    n = 0
    for q in QUESTIONS:
        acc = q.acceptable(graph)
        ans = data.get(q.id, data.get(q.id.split("_")[0]))  # files key short ids (Q1)
        try:
            got = run_cypher(conn, ans) if isinstance(ans, str) and ans.strip() else frozenset()
            status = "PASS" if _ok(got, acc) else "FAIL"
        except Exception as exc:  # noqa: BLE001 — Cypher error = miss, not crash
            status, got = f"ERROR({type(exc).__name__})", frozenset()
        n += status == "PASS"
        print(f"  {q.id:<22}{status}")
        if status != "PASS":
            truth = acc[0]
            miss = sorted(truth - got)[:3]; extra = sorted(got - truth)[:3]
            print(f"      truth={sorted(truth)[:3]}… miss={miss} extra={extra}")
    print(f"  {'-'*70}\n  {surface} total: {n}/{len(QUESTIONS)}\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    graph, _, _ = build_kg(CORPUS)
    conn = load_kuzu(graph)
    rc = validate_oracles(graph, conn)
    if "--replay" in argv:
        path = argv[argv.index("--replay") + 1]
        surface = argv[argv.index("--surface") + 1] if "--surface" in argv else "cypher"
        if not Path(path).is_absolute():
            path = str(Path(__file__).resolve().parent / path)
        grade_replay(graph, conn, surface, path)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
