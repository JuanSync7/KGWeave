"""Ralph-loop edge cases for the Origin round-trip surface.

Each test is a falsifiable claim about a corner the I1 gate doesn't
exercise directly: empty files, multi-byte UTF-8, CRLF, zero-length and
end-of-file spans, embedded NUL bytes, large files, malformed offsets,
and over-the-end slicing.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from knowledge_graph.store.spans import OriginNotFoundError


def test_empty_file_snapshots_and_zero_span_returns_empty(tmp_store, tmp_path: Path):
    """An empty file is a valid origin; only the [0:0] span is meaningful."""
    p = tmp_path / "empty.sv"
    p.write_bytes(b"")
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    assert ref.sha256  # sha of empty bytes is the canonical e3b0... value
    assert tmp_store.source_at(ref.id, 0, 0) == b""


def test_zero_length_span_in_nonempty_file_returns_empty(tmp_store, tmp_path: Path):
    """[k:k] for any in-range k must return ``b''`` regardless of content."""
    p = tmp_path / "nonempty.sv"
    p.write_bytes(b"module a; endmodule\n")
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    for k in (0, 1, 5, 10, 19, 20):
        assert tmp_store.source_at(ref.id, k, k) == b""


def test_span_at_exact_end_of_file(tmp_store, tmp_path: Path):
    """[n-3:n] and [n:n] must round-trip when n == file length."""
    p = tmp_path / "eof.sv"
    body = b"abcdefghij"  # 10 bytes
    p.write_bytes(body)
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    assert tmp_store.source_at(ref.id, 7, 10) == b"hij"
    assert tmp_store.source_at(ref.id, 10, 10) == b""


def test_multibyte_utf8_offsets_are_bytes_not_chars(tmp_store, tmp_path: Path):
    """A 2-byte UTF-8 char must occupy exactly 2 byte offsets in spans."""
    p = tmp_path / "utf8.sv"
    # 'é' = 0xc3 0xa9 — two bytes, one char
    body = "// é signal\n".encode("utf-8")
    p.write_bytes(body)
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    # Byte 3..5 must be the 'é' bytes plus the following space
    assert tmp_store.source_at(ref.id, 3, 5) == b"\xc3\xa9"
    assert tmp_store.source_at(ref.id, 3, 6) == b"\xc3\xa9 "
    # full round-trip
    assert tmp_store.source_at(ref.id, 0, len(body)) == body


def test_crlf_line_endings_are_preserved(tmp_store, tmp_path: Path):
    """CR and LF bytes must survive the snapshot intact (no normalisation)."""
    p = tmp_path / "crlf.sv"
    body = b"module x;\r\n  // hi\r\nendmodule\r\n"
    p.write_bytes(body)
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    out = tmp_store.source_at(ref.id, 0, len(body))
    assert out == body
    # spot check that \r is at offset 9 (after "module x;")
    assert tmp_store.source_at(ref.id, 9, 11) == b"\r\n"


def test_nul_and_high_bytes_round_trip(tmp_store, tmp_path: Path):
    """Embedded NUL and 0x80-0xFF bytes must survive via the latin-1 codec."""
    p = tmp_path / "binary.bin"
    body = bytes(range(256)) * 4  # 1024 bytes covering every value
    p.write_bytes(body)
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    assert tmp_store.source_at(ref.id, 0, len(body)) == body
    # spot-check the embedded NUL is preserved at offsets 0, 256, 512, 768
    for off in (0, 256, 512, 768):
        assert tmp_store.source_at(ref.id, off, off + 1) == b"\x00"


def test_large_file_random_spans(tmp_store, tmp_path: Path):
    """A 1 MiB synthetic file with random spans round-trips byte-exact."""
    p = tmp_path / "big.bin"
    body = os.urandom(1 << 20)  # 1 MiB
    p.write_bytes(body)
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    rng = random.Random(0xDEADBEEF)
    n = len(body)
    for _ in range(50):
        start = rng.randint(0, n)
        end = rng.randint(start, n)
        assert tmp_store.source_at(ref.id, start, end) == body[start:end]


def test_negative_offset_rejected(tmp_store, tmp_path: Path):
    """``source_at`` must reject negative offsets rather than wrap python-style."""
    p = tmp_path / "n.sv"
    p.write_bytes(b"hello")
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    with pytest.raises(ValueError):
        tmp_store.source_at(ref.id, -1, 3)
    with pytest.raises(ValueError):
        tmp_store.source_at(ref.id, 0, -1)


def test_end_before_start_rejected(tmp_store, tmp_path: Path):
    """end_offset < start_offset is a programming error, not an empty slice."""
    p = tmp_path / "n.sv"
    p.write_bytes(b"hello")
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    with pytest.raises(ValueError):
        tmp_store.source_at(ref.id, 4, 2)


def test_over_end_offset_clamps_like_python_slice(tmp_store, tmp_path: Path):
    """An end_offset past EOF returns whatever bytes exist — same as ``[k:big]``."""
    p = tmp_path / "n.sv"
    p.write_bytes(b"hello")
    ref = tmp_store.snapshot_file(p, source="sv", corpus="edge")
    assert tmp_store.source_at(ref.id, 0, 999) == b"hello"
    assert tmp_store.source_at(ref.id, 4, 999) == b"o"


def test_unknown_origin_raises_not_found(tmp_store):
    """The error type is ``OriginNotFoundError`` (a KeyError subtype)."""
    with pytest.raises(OriginNotFoundError):
        tmp_store.source_at("origin:does-not-exist", 0, 1)
