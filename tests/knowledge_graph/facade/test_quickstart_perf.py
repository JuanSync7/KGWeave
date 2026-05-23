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
v1.5-#2 replaced the per-row Cypher MERGE loop in the SV writer with
a Kuzu ``COPY FROM`` bulk path for any batch of >=100 rows. The
quickstart wall-clock fell from ~125 s to ~1.4 s (worst-of-3 was
1.452 s) -- a ~90x speedup. The cap had to be raised from 256 MiB to
1 GiB because COPY needs more buffer-manager frame groups than the
prior cap allowed (Kuzu raised "No more frame groups can be added to
the allocator" otherwise).

Worst-of-3 was 1.452 s; 1.452 * 1.5 ~= 2.2 s, but subprocess startup
+ cold imports add ~1 s of jitter on this box. The budget below is
10 s -- still a 20x tightening from the prior 200 s floor, with
~7 s of headroom so the test doesn't flap under load.

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

# v1.5-#2: bulk-COPY writer path now dominates -- quickstart wall fell
# from ~125 s to ~1.4 s (3-run worst 1.452 s on this box, ~90x speedup
# vs the v1.5-#1 baseline). The cap was raised from 256 MiB to 1 GiB
# in the env block below because the COPY path needs more buffer-
# manager frame groups than 256 MiB allowed.
#
# Budget: 1.45 * 1.5 ~= 2.2 s, but subprocess startup + cold imports
# add ~1 s of jitter on a noisy box. Floor set to 10 s -- still a
# 20x tightening from the prior 200 s floor, with ~7 s of headroom so
# the test doesn't flap on CI under load. See JOURNAL v1.5-#2.
_BUDGET_SECONDS = 10.0


@pytest.mark.perf
@pytest.mark.timeout(_BUDGET_SECONDS + 60)
def test_quickstart_wall_clock_under_budget(tmp_path: Path) -> None:
    """Quickstart subprocess must finish in under the perf floor."""
    store_path = tmp_path / "qs.kuzu"
    # Forward the 256 MiB cap so the subprocess opens its Kuzu store
    # the same way the in-process test fixtures do. Without this env
    # var the quickstart uses Kuzu's 8 TB default and the ext4 sparse-
    # allocation cost (~125 s) eats the entire margin.
    # v1.5-#2: bulk-COPY needs a larger buffer-manager allocation than the
    # 256 MiB cap allowed (COPY raised "No more frame groups can be added
    # to the allocator"). Raised to 1 GiB -- still bounds the footprint
    # well below Kuzu's 8 TB default, and the COPY path completes.
    env = {**os.environ, "KGWEAVE_MAX_DB_SIZE_BYTES": "1073741824"}
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
