"""Smoke-test that the quickstart script runs end-to-end."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_quickstart_script_runs_end_to_end(tmp_path: Path) -> None:
    # Subprocess timeout: 240s (not 120s).
    #
    # The conftest pins ``basetemp`` to ``~/.pytest-tmp`` on the root ext4
    # filesystem (v1.4-#1, to prevent /tmp tmpfs blowups). Kuzu store I/O
    # against ext4 is ~4x slower than tmpfs because Kuzu's default
    # ``max_db_size`` (8 TB) is sparse-allocated on disk -- on tmpfs the
    # sparse holes are free, on ext4 the metadata + checkpoint fsyncs are
    # not. Measured worst-of-3 wall-clock on this box is ~152s for the
    # 2-file SV fixture (best ~124s); 240s leaves a ~60% headroom for
    # jitter. See ``tests/knowledge_graph/facade/test_quickstart_perf.py``
    # for the perf regression floor that catches a real slowdown earlier.
    store_path = tmp_path / "qs.kuzu"
    proc = subprocess.run(
        [sys.executable, "-m", "knowledge_graph.examples.quickstart", str(store_path)],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert proc.returncode == 0, (
        f"quickstart exited {proc.returncode}\n--- stdout ---\n{proc.stdout}"
        f"\n--- stderr ---\n{proc.stderr}"
    )
    # At least one line mentions modules:count=
    assert "modules: count=" in proc.stdout
    assert "raw cypher rows:" in proc.stdout
    assert "extract:" in proc.stdout
