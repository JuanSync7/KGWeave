"""Smoke-test that the quickstart script runs end-to-end."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_quickstart_script_runs_end_to_end(tmp_path: Path) -> None:
    # Subprocess timeout: 400 s.
    #
    # The conftest pins ``basetemp`` to ``~/.pytest-tmp`` on the root ext4
    # filesystem (v1.4-#1, to prevent /tmp tmpfs blowups). v1.5-#1 added
    # the ``KGWEAVE_MAX_DB_SIZE_BYTES`` env var so the quickstart can cap
    # Kuzu's mmap reservation (256 MiB for tests); re-measurement showed
    # the cap correctly bounds on-disk size but does NOT move wall-clock
    # (extract dominates at ~125 s; see test_quickstart_perf.py and
    # JOURNAL v1.5-#1). Three runs on this box measured 124-127 s; the
    # perf-floor test in ``test_quickstart_perf.py`` is now pinned at
    # 200 s. This smoke-test timeout is set per the v1.5-#1 rule
    # ``max(perf_floor + 60, 2 * perf_floor) = max(260, 400) = 400`` so
    # the smoke covers any case the perf-floor would still let through.
    store_path = tmp_path / "qs.kuzu"
    proc = subprocess.run(
        [sys.executable, "-m", "knowledge_graph.examples.quickstart", str(store_path)],
        capture_output=True,
        text=True,
        timeout=400,
    )
    assert proc.returncode == 0, (
        f"quickstart exited {proc.returncode}\n--- stdout ---\n{proc.stdout}"
        f"\n--- stderr ---\n{proc.stderr}"
    )
    # At least one line mentions modules:count=
    assert "modules: count=" in proc.stdout
    assert "raw cypher rows:" in proc.stdout
    assert "extract:" in proc.stdout
