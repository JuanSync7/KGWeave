"""Behavioural check that ``max_db_size_bytes`` actually bounds on-disk size.

v1.5-#1 / G2.

The G1 tests (``test_kgstore_max_db_size.py``) only verify that the kwarg
exists on :meth:`KGStore.open` and is forwarded to ``kuzu.Database`` as
``max_db_size``. That is the load-bearing contract because Kuzu's
documentation describes ``max_db_size`` as a workaround for the 8 TB
mmap address-space limit -- it caps the *reservation*, not necessarily
the *write throughput*.

This test goes one step further: open a store with a 256 MiB cap, do a
meaningful sequence of writes (a few hundred ``:Origin`` rows + an
``init_schema`` round-trip), then assert the resulting on-disk directory
footprint stays comfortably below the cap. The write volume here is
~tens of KB of payload, so the *real* thing being measured is whether
Kuzu pre-allocates / sparse-allocates a multi-GB file on open or whether
the cap is honoured.

Rationale for the threshold
---------------------------
The expected on-disk footprint of a fresh ``init_schema``'d store with a
few hundred small rows is < 5 MB on ext4. We assert ``< 256 MiB`` (the
cap) with a wide margin -- the goal is to catch the regression where
either (a) we forget to pass ``max_db_size`` through to Kuzu, in which
case the default 8 TB sparse reservation would push the directory size
well past 256 MiB on ext4, or (b) Kuzu silently grows past the cap.

If Kuzu's binding ever changes so that the cap is enforced at write
time and starts raising on overflow, that's a *good* signal -- we'd
keep the assertion. If the binding ever ignores the cap entirely on
this platform, the directory size jumps above 256 MiB and this test
fails, signalling that we need to fall back to the G1
forwarded-arg-only contract (see JOURNAL v1.5-#1).
"""

from __future__ import annotations

from pathlib import Path

from knowledge_graph.store import KGStore


_CAP_BYTES = 268_435_456  # 256 MiB, power of 2 (Kuzu requirement)


def _dir_size_bytes(p: Path) -> int:
    """Total size of every regular file under ``p`` (apparent size).

    We use ``stat().st_size`` (apparent size) rather than
    ``st_blocks * 512`` (allocated blocks) because the failure mode we
    care about is Kuzu writing/declaring a giant sparse file -- the
    apparent size is what blows up first when the cap is missing.
    """
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                # Concurrent rotation -- treat as zero, the next pass
                # picks it up. Should never happen for this test
                # because the store is single-process.
                pass
    return total


def test_capped_store_on_disk_size_stays_under_cap(tmp_path: Path) -> None:
    """A 256 MiB-capped store must not balloon to multi-GB on ext4."""
    store_path = tmp_path / "kg.kuzu"
    store = KGStore.open(store_path, max_db_size_bytes=_CAP_BYTES)
    try:
        # Write a few hundred Origin rows -- enough payload to force
        # Kuzu to actually allocate node-table pages, but tiny in
        # absolute terms (each row is well under 1 KB).
        for i in range(200):
            store.conn.execute(
                """
                CREATE (:Origin {
                    id: $id,
                    uri: $uri,
                    sha256: $sha,
                    content: '',
                    byte_length: 0,
                    source: 'g2-behaviour',
                    corpus: 'g2-behaviour',
                    lang: ''
                })
                """,
                {
                    "id": f"g2-{i:04d}",
                    "uri": f"file:///g2/{i:04d}.sv",
                    "sha": f"{i:064x}",
                },
            )
        # Checkpoint so any deferred WAL writes land.
        store.conn.execute("CHECKPOINT;")
    finally:
        store.close()

    on_disk = _dir_size_bytes(store_path)
    assert on_disk < _CAP_BYTES, (
        f"Capped store on-disk size {on_disk} bytes exceeded the "
        f"256 MiB cap ({_CAP_BYTES} bytes). Either the cap is not "
        "being forwarded to kuzu.Database, or Kuzu is silently "
        "growing past max_db_size. See JOURNAL v1.5-#1."
    )
