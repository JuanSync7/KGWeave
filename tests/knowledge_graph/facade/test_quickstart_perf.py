"""Wall-clock perf regression floor for the quickstart subprocess.

Why this test exists
--------------------
The companion smoke test ``test_quickstart_runs.py`` only asserts that the
quickstart eventually completes (with a 240s subprocess timeout). That is
enough to catch *correctness* regressions but does nothing to catch a
*perf* regression that doubles or triples the wall-clock while still
fitting under the smoke-test budget. This test pins a floor so a 2x
slowdown trips a clean fail rather than silently eating into the smoke
margin.

How the budget was chosen
-------------------------
Measured wall-clock on the dev box (ext4 ``~/.pytest-tmp`` basetemp,
v1.4-#1 infra) for the 2-file SV fixture is ~130s. The budget below is
``ceil(measured * 1.5)`` rounded up to the nearest 5 -- i.e. 200s. This
gives a ~50% headroom for jitter (concurrent I/O, cold caches, etc.)
without losing the ability to catch a real 2x regression.

If the test flakes
------------------
First try running it three times in a row. If only one of three fails,
the issue is jitter -- widen the budget or convert to median-of-3. If
all three fail consistently, you have a genuine regression -- profile
with ``KGWEAVE_QS_PROFILE=1`` (env var honoured by
``src/knowledge_graph/examples/quickstart.py``) to find the stage that
got slower.

How to skip
-----------
``pytest -m 'not perf'`` deselects this test (and any other ``@perf``
tests). Useful for fast inner-loop runs where you don't care about the
wall-clock floor.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

# Budget: worst-of-3 measured wall-clock was 152s on the dev box (ext4
# basetemp); 152 * 1.5 = 228, rounded up to nearest 5 = 230. The other
# two of three runs were 124s and 134s, so the floor leaves ~70-100s of
# slack on a quiet box and ~75s on a noisy one. See module docstring
# for the full derivation.
_BUDGET_SECONDS = 230.0


@pytest.mark.perf
@pytest.mark.timeout(_BUDGET_SECONDS + 60)
def test_quickstart_wall_clock_under_budget(tmp_path: Path) -> None:
    """Quickstart subprocess must finish in under the perf floor."""
    store_path = tmp_path / "qs.kuzu"
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "knowledge_graph.examples.quickstart", str(store_path)],
        capture_output=True,
        text=True,
        timeout=_BUDGET_SECONDS + 30,
    )
    elapsed = time.perf_counter() - start

    assert proc.returncode == 0, (
        f"quickstart exited {proc.returncode}\n--- stdout ---\n{proc.stdout}"
        f"\n--- stderr ---\n{proc.stderr}"
    )
    assert elapsed < _BUDGET_SECONDS, (
        f"quickstart wall-clock {elapsed:.1f}s exceeded perf floor "
        f"{_BUDGET_SECONDS:.0f}s -- something regressed. Re-run with "
        f"KGWEAVE_QS_PROFILE=1 to locate the slow stage."
    )
