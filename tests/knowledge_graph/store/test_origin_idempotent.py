"""Idempotent snapshot semantics + content-change semantics."""

from __future__ import annotations

from pathlib import Path


def _origin_count(store) -> int:
    res = store.conn.execute("MATCH (o:Origin) RETURN count(o)")
    return res.get_next()[0]


def test_resnapshot_same_file_is_noop(tmp_store, tmp_path: Path):
    """Snapshotting the same path+content twice returns the same id and adds no rows."""
    p = tmp_path / "a.sv"
    p.write_text("module a; endmodule\n")
    ref1 = tmp_store.snapshot_file(p, source="sv", corpus="fixtures")
    n1 = _origin_count(tmp_store)
    ref2 = tmp_store.snapshot_file(p, source="sv", corpus="fixtures")
    n2 = _origin_count(tmp_store)
    assert ref1.id == ref2.id
    assert ref1.sha256 == ref2.sha256
    assert n1 == n2 == 1


def test_snapshot_after_content_change_produces_new_origin(tmp_store, tmp_path: Path):
    """Changing the file content yields a fresh origin row; both remain resolvable."""
    p = tmp_path / "b.sv"
    p.write_text("module b; endmodule\n")
    ref1 = tmp_store.snapshot_file(p, source="sv", corpus="fixtures")
    p.write_text("module b2; endmodule\n")
    ref2 = tmp_store.snapshot_file(p, source="sv", corpus="fixtures")
    assert ref1.id != ref2.id
    assert ref1.sha256 != ref2.sha256
    assert _origin_count(tmp_store) == 2
    # both contents still resolvable
    assert tmp_store.source_at(ref1.id, 0, 8) == b"module b"
    assert tmp_store.source_at(ref2.id, 0, 9) == b"module b2"


def test_two_paths_same_content_get_distinct_origins(tmp_store, tmp_path: Path):
    """Two files with the same content but different URIs are stored as two rows.

    Rationale: origin id is keyed on (uri, sha) so deletion of one file does not
    invalidate the other's spans.
    """
    p1 = tmp_path / "x.sv"
    p2 = tmp_path / "y.sv"
    body = "module same; endmodule\n"
    p1.write_text(body)
    p2.write_text(body)
    ref1 = tmp_store.snapshot_file(p1, source="sv", corpus="fixtures")
    ref2 = tmp_store.snapshot_file(p2, source="sv", corpus="fixtures")
    assert ref1.sha256 == ref2.sha256
    assert ref1.id != ref2.id
    assert _origin_count(tmp_store) == 2
