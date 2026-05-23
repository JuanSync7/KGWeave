"""Smoke-test that the quickstart script runs end-to-end."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_quickstart_script_runs_end_to_end(tmp_path: Path) -> None:
    # Subprocess timeout: 70 s.
    #
    # The conftest pins ``basetemp`` to ``~/.pytest-tmp`` on the root ext4
    # filesystem (v1.4-#1, to prevent /tmp tmpfs blowups). v1.5-#2 swapped
    # the SV writer onto a Kuzu ``COPY FROM`` bulk path for batches of
    # >=100 rows; quickstart wall-clock fell from ~125 s to ~1.4 s. The
    # perf-floor test in ``test_quickstart_perf.py`` is now pinned at
    # 10 s. This smoke-test timeout is set per the v1.5-#1 rule
    # ``max(perf_floor + 60, 2 * perf_floor) = max(70, 20) = 70`` so the
    # smoke covers any case the perf-floor would still let through (and
    # leaves ~60 s of head-room above the floor for cold-import jitter).
    store_path = tmp_path / "qs.kuzu"
    proc = subprocess.run(
        [sys.executable, "-m", "knowledge_graph.examples.quickstart", str(store_path)],
        capture_output=True,
        text=True,
        timeout=70,
    )
    assert proc.returncode == 0, (
        f"quickstart exited {proc.returncode}\n--- stdout ---\n{proc.stdout}"
        f"\n--- stderr ---\n{proc.stderr}"
    )
    # At least one line mentions modules:count=
    assert "modules: count=" in proc.stdout
    assert "raw cypher rows:" in proc.stdout
    assert "extract:" in proc.stdout
