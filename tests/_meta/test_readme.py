"""Goal 5: tests/README.md exists and documents the pytest infra guards."""
from __future__ import annotations

from pathlib import Path


_README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_exists() -> None:
    assert _README.exists(), f"missing {_README}"


def test_readme_mentions_guards() -> None:
    text = _README.read_text().lower()
    for needle in ("basetemp", "timeout", "lockfile", "kuzu"):
        assert needle in text, f"tests/README.md must mention {needle!r}"
