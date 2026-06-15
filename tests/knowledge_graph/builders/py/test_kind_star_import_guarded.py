"""v1.12-#3: ``is_star`` AND ``import_guard`` combine on guarded star-imports.

A ``from X import *`` inside ``if TYPE_CHECKING:`` or
``try: ... except ImportError:`` must carry BOTH ``is_star=True`` AND
the correct ``import_guard`` payload value. The two walker payload writes
are independent today (v1.10-#3 sets ``is_star``; v1.8-#2 sets
``import_guard``) and we pin that combination here.
"""

from __future__ import annotations

from pathlib import Path

from knowledge_graph.builders.py.walker import lift_python

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


def _imports(path: Path) -> list[dict[str, object]]:
    nodes = lift_python(path.read_bytes())
    return [n.payload for n in nodes if n.kind == "PyImport"]


def test_star_in_type_checking_block_combines_is_star_and_guard() -> None:
    payloads = _imports(FIXTURE_DIR / "star_type_checking.py")
    star = [p for p in payloads if p.get("module") == "star_target"]
    assert len(star) == 1, payloads
    assert star[0].get("is_star") is True, star[0]
    assert star[0].get("import_guard") == "type-checking", star[0]


def test_star_in_try_import_block_combines_is_star_and_guard() -> None:
    payloads = _imports(FIXTURE_DIR / "star_try_import.py")
    star = [p for p in payloads if p.get("module") == "star_target"]
    assert len(star) == 1, payloads
    assert star[0].get("is_star") is True, star[0]
    assert star[0].get("import_guard") == "try-import", star[0]
