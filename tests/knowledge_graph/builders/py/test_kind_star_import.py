"""v1.10-#3: ``is_star`` flag on PyImport payload for ``from X import *``.

Contract: every PyImport row carries an ``is_star: bool`` payload key.
``True`` for ``from X import *``; ``False`` for every other import shape.
"""

from __future__ import annotations

from pathlib import Path

from knowledge_graph.builders.py.walker import lift_python

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


def _imports(path: Path) -> list[dict[str, object]]:
    nodes = lift_python(path.read_bytes())
    return [n.payload for n in nodes if n.kind == "PyImport"]


def test_from_star_import_marks_is_star_true() -> None:
    payloads = _imports(FIXTURE_DIR / "star_consumer.py")
    star = [p for p in payloads if p.get("module") == "star_target"]
    assert len(star) == 1
    assert star[0].get("is_star") is True
    # All other (e.g. ``from __future__``) must explicitly mark False.
    for p in payloads:
        if p.get("module") != "star_target":
            assert p.get("is_star") is False, p


def test_named_from_import_marks_is_star_false() -> None:
    payloads = _imports(FIXTURE_DIR / "crossfile_capture_b.py")
    assert len(payloads) >= 1
    for p in payloads:
        assert p.get("is_star") is False, p


def test_plain_import_marks_is_star_false() -> None:
    payloads = _imports(FIXTURE_DIR / "module_capture_b.py")
    assert len(payloads) >= 1
    for p in payloads:
        assert p.get("is_star") is False, p
