"""Shared writer helpers used by every per-language builder writer.

v1.7-#1: lifted out of ``builders/sv/writer.py`` so the Python writer
(and any future builder) can depend on a stable, public surface instead
of reaching into another builder's private namespace.

Contents:

* :data:`BULK_COPY_MIN_ROWS` -- per-row vs COPY-FROM crossover threshold.
* :data:`NODE_CSV_COLUMNS`   -- canonical column order for the ``:Node``
  table CSV used by every bulk-COPY writer.
* :func:`node_row_for_csv`   -- project a per-node params dict to a CSV
  row matching :data:`NODE_CSV_COLUMNS`.
* :func:`detach_delete_node_ids` -- chunked ``DETACH DELETE`` to clear a
  set of Node PKs before a replacement bulk COPY.
* :func:`copy_csv` -- write rows to a temp CSV and ``COPY <table> FROM``
  it, with header-row guard and tmpfile cleanup.

Names are module-public (no leading underscore) but the module itself is
private to the ``builders`` package (``_writer_common``). Consumers
outside ``builders/`` must continue to go through the public facade.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any


# v1.5-#2: row-count threshold above which write_graph switches from the
# per-row Cypher MERGE loop to a Kuzu ``COPY FROM`` bulk path. Justified
# by a micro-bench on this box (see ``tests/.../test_writer_perf.py``):
# baseline per-row cost is ~10 ms/row across N=10/100/1000; the bulk path
# pays a fixed CSV-serialise + flush + COPY-parse cost that only amortises
# above ~100 rows. Below the threshold the per-row loop wins on overhead.
BULK_COPY_MIN_ROWS: int = 100

# Node-PK chunk size for the pre-COPY DETACH DELETE. Kuzu accepts list
# parameters, but very large lists slow the IN-list scan; 1000 keeps the
# delete latency negligible for realistic batches (~10k nodes/file).
_DELETE_CHUNK: int = 1000


NODE_CSV_COLUMNS: tuple[str, ...] = (
    "id", "kind", "category", "name", "source", "corpus", "origin_id",
    "start_offset", "end_offset", "start_line", "end_line",
    "start_col", "end_col", "payload",
)


def node_row_for_csv(params: dict[str, Any]) -> list[Any]:
    """Project a per-node params dict to a CSV row matching the
    :data:`NODE_CSV_COLUMNS` order. ``None`` is emitted as the empty
    string -- Kuzu COPY treats unquoted empties as NULL for nullable
    columns (``name`` is nullable; the other STRING columns are written
    as concrete values upstream so the empty-as-NULL ambiguity does not
    bite)."""
    return [params[c] if params[c] is not None else "" for c in NODE_CSV_COLUMNS]


def detach_delete_node_ids(conn: Any, ids: list[str]) -> None:
    """DETACH DELETE the given Node IDs in chunks.

    Run before the bulk COPY so the replacement-merge contract is
    preserved without violating the COPY uniqueness constraint. DETACH
    also wipes every incident REL row, which is what we want -- the
    follow-up COPY of the typed REL tables replays them fresh.
    """
    if not ids:
        return
    for i in range(0, len(ids), _DELETE_CHUNK):
        chunk = ids[i:i + _DELETE_CHUNK]
        conn.execute(
            "MATCH (n:Node) WHERE n.id IN $ids DETACH DELETE n",
            {"ids": chunk},
        )


def copy_csv(conn: Any, table: str, header: tuple[str, ...],
             rows: list[list[Any]], tmpdir: Path) -> None:
    """Write ``rows`` to a CSV under ``tmpdir`` and ``COPY <table> FROM`` it.

    Empty ``rows`` is a no-op (COPY of zero records is wasted I/O and
    Kuzu's parser still pays for it). The CSV writes the header row so
    we can pass ``header=true`` to Kuzu and stay column-order-agnostic
    on the writer side -- Kuzu still requires the column NAMES to match
    the table schema."""
    if not rows:
        return
    # Distinct file per call so concurrent REL COPYs (sequential here,
    # but the per-table loop reuses tmpdir) don't collide.
    fd, path = tempfile.mkstemp(prefix=f"copy_{table}_", suffix=".csv", dir=tmpdir)
    try:
        with open(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        # Escape backslashes in the path for the Cypher literal (Windows
        # paths would otherwise break; harmless on POSIX).
        path_lit = path.replace("\\", "\\\\")
        conn.execute(f"COPY {table} FROM '{path_lit}' (header=true)")
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass
