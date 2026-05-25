"""v1.8-#2: closed ``import_guard`` payload for conditional PyImports.

Closed value set:
  {"type-checking", "try-import", "version-guard", "conditional", None}

Top-level / def-or-class-nested imports without any wrapping ``if`` or
``try`` carry no ``import_guard`` key (treated as ``None``).
"""
from __future__ import annotations

from pathlib import Path

from knowledge_graph.builders.py.walker import lift_python

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"


def _imports_by_primary(path: Path) -> dict[str, dict[str, object]]:
    nodes = lift_python(path.read_bytes())
    return {
        n.name: n.payload for n in nodes if n.kind == "PyImport"
    }


def test_try_except_import_marks_try_import() -> None:
    by_primary = _imports_by_primary(FIXTURE_DIR / "import_try_except.py")
    # `json` is a plain top-level runtime import: no guard.
    assert by_primary["json"].get("import_guard") in (None,)
    assert by_primary["json"].get("runtime") is True
    # `ujson` and the fallback `json as ujson` are inside try/except.
    assert by_primary["ujson"].get("import_guard") == "try-import"
    assert by_primary["ujson"].get("runtime") is True


def test_version_guard_import_marks_version_guard() -> None:
    by_primary = _imports_by_primary(FIXTURE_DIR / "import_version_guard.py")
    assert by_primary["sys"].get("import_guard") in (None,)
    assert by_primary["tomllib"].get("import_guard") == "version-guard"
    assert by_primary["tomllib"].get("runtime") is True


def test_plain_conditional_import_marks_conditional() -> None:
    by_primary = _imports_by_primary(FIXTURE_DIR / "import_conditional.py")
    assert by_primary["os"].get("import_guard") in (None,)
    assert by_primary["optional_dep"].get("import_guard") == "conditional"
    assert by_primary["optional_dep"].get("runtime") is True


def test_type_checking_import_marks_type_checking_and_preserves_runtime_false() -> None:
    by_primary = _imports_by_primary(FIXTURE_DIR / "type_checking.py")
    # Pre-existing v1.6-#3 contract preserved.
    assert by_primary["sys"].get("runtime") is True
    assert by_primary["collections"].get("runtime") is False
    # New v1.8-#2 contract layered on top.
    assert by_primary["sys"].get("import_guard") in (None,)
    assert by_primary["collections"].get("import_guard") == "type-checking"


def test_import_guard_values_are_in_closed_set() -> None:
    closed = {"type-checking", "try-import", "version-guard", "conditional", None}
    for fixture in (
        "import_try_except.py",
        "import_version_guard.py",
        "import_conditional.py",
        "type_checking.py",
    ):
        by_primary = _imports_by_primary(FIXTURE_DIR / fixture)
        for payload in by_primary.values():
            assert payload.get("import_guard") in closed
