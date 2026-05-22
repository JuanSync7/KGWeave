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
v1.5-#1 introduced ``KGWEAVE_MAX_DB_SIZE_BYTES`` so the quickstart
subprocess can cap Kuzu's mmap reservation at 256 MiB, on the hypothesis
that Kuzu's 8 TB default was sparse-allocating on ext4 and inflating
wall-clock. Re-measurement on this box with the cap forwarded *did not*
move the needle: three runs measured 125.58 s, 126.91 s, 124.69 s
(with cap) -- effectively identical to the v1.4-#4 baseline of
~124-152 s without cap. Profile shows the time is spent inside
``extract`` (~125 s), not in ``open_store`` (~0.6 s). The cap is still
forwarded (it correctly bounds the on-disk footprint to ~127 MB, which
is hygienic) but it does not buy back wall-clock. See JOURNAL v1.5-#1.

Worst-of-3 was 126.91 s; ``ceil(127 * 1.5)`` rounded up to nearest 5
is 195. The budget below is 200 s -- a modest tightening from the prior
230 s floor, still leaving ~70 s of headroom for jitter without
flapping on a noisy box.

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

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# v1.5-#1: With the 256 MiB Kuzu max_db_size cap forwarded into the
# quickstart subprocess (via KGWEAVE_MAX_DB_SIZE_BYTES below) the cap
# did NOT move wall-clock on this box (3-run worst-case 126.91 s, vs
# ~124-152 s without cap; extract dominates at ~125 s, open_store is
# ~0.6 s). Budget: ceil(127 * 1.5) rounded up to nearest 5 == 195;
# we set 200 s -- a modest tightening from the prior v1.4-#4 floor of
# 230 s. See module docstring + JOURNAL v1.5-#1 for the full retro.
_BUDGET_SECONDS = 200.0


@pytest.mark.perf
@pytest.mark.timeout(_BUDGET_SECONDS + 60)
def test_quickstart_wall_clock_under_budget(tmp_path: Path) -> None:
    """Quickstart subprocess must finish in under the perf floor."""
    store_path = tmp_path / "qs.kuzu"
    # Forward the 256 MiB cap so the subprocess opens its Kuzu store
    # the same way the in-process test fixtures do. Without this env
    # var the quickstart uses Kuzu's 8 TB default and the ext4 sparse-
    # allocation cost (~125 s) eats the entire margin.
    env = {**os.environ, "KGWEAVE_MAX_DB_SIZE_BYTES": "268435456"}
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "knowledge_graph.examples.quickstart", str(store_path)],
        capture_output=True,
        text=True,
        timeout=_BUDGET_SECONDS + 30,
        env=env,
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
