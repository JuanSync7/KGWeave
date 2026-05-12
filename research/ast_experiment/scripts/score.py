"""Score = #AST classes touched by fifo.sv NOT yet covered by passing round-trip cases.

Coverage source: ast_classes.json (full set, written by inventory.py)
                 covered_classes.json (subset, written by tests on pass)

Run:  uv run python research/ast_experiment/scripts/score.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ALL = HERE / "ast_classes.json"
COV = HERE / "covered_classes.json"


def main() -> int:
    if not ALL.exists():
        print("missing ast_classes.json — run inventory.py first", file=sys.stderr)
        return 2
    all_classes = set(json.loads(ALL.read_text()))
    covered = set(json.loads(COV.read_text())) if COV.exists() else set()
    missing = sorted(all_classes - covered)
    print(f"score = {len(missing)}")
    print(f"covered = {len(covered)} / {len(all_classes)}")
    for m in missing:
        print(f"  MISSING {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
