"""I1 gate: source round-trip — random byte ranges over every SV fixture."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sv"
RANDOM_RANGES_PER_FILE = 100
RNG_SEED = 0xC0FFEE


def _sv_fixtures() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.sv"))


@pytest.fixture(scope="module")
def sv_fixtures() -> list[Path]:
    files = _sv_fixtures()
    assert files, f"no SV fixtures found under {FIXTURES_DIR}"
    return files


def test_snapshot_returns_origin_id_and_sha(tmp_store, sv_fixtures):
    """snapshot_file must return an OriginRef carrying id + sha256."""
    path = sv_fixtures[0]
    ref = tmp_store.snapshot_file(path, source="sv", corpus="fixtures")
    assert ref.id
    assert ref.sha256
    assert ref.uri.endswith(path.name)


def test_source_at_matches_file_bytes_random_spans(tmp_store, sv_fixtures):
    """For every SV fixture, 100 random byte ranges must round-trip exactly."""
    rng = random.Random(RNG_SEED)
    mismatches: list[str] = []

    for path in sv_fixtures:
        raw = path.read_bytes()
        ref = tmp_store.snapshot_file(path, source="sv", corpus="fixtures")
        n = len(raw)
        for _ in range(RANDOM_RANGES_PER_FILE):
            if n == 0:
                start = end = 0
            else:
                start = rng.randint(0, n)
                end = rng.randint(start, n)
            expected = raw[start:end]
            actual = tmp_store.source_at(ref.id, start, end)
            if actual != expected:
                mismatches.append(
                    f"{path.name}[{start}:{end}] expected {expected!r} got {actual!r}"
                )
                if len(mismatches) > 5:
                    break

    assert not mismatches, "\n".join(mismatches[:5])


def test_source_at_unknown_origin_raises(tmp_store):
    """Asking for a slice of an unknown origin must raise, not silently return b''."""
    from knowledge_graph.store.spans import OriginNotFoundError

    with pytest.raises(OriginNotFoundError):
        tmp_store.source_at("does-not-exist", 0, 10)
