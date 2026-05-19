"""Smoke-test that the quickstart script runs end-to-end."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_quickstart_script_runs_end_to_end(tmp_path: Path) -> None:
    store_path = tmp_path / "qs.kuzu"
    proc = subprocess.run(
        [sys.executable, "-m", "knowledge_graph.examples.quickstart", str(store_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"quickstart exited {proc.returncode}\n--- stdout ---\n{proc.stdout}"
        f"\n--- stderr ---\n{proc.stderr}"
    )
    # At least one line mentions modules:count=
    assert "modules: count=" in proc.stdout
    assert "raw cypher rows:" in proc.stdout
    assert "extract:" in proc.stdout
