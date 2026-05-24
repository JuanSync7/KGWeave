"""Meta test: no cross-builder private-name imports.

v1.7-#1: Until ``_writer_common`` was lifted, ``builders/py/writer.py``
imported five private names from ``builders/sv/writer.py``. That coupling
made every new builder a three-way private-import pile-up. This test
locks the boundary closed -- builders may only share via the public
``_writer_common`` module.

The grep mirrors the charter's validation:
    grep -rn "from.*\\.sv\\.writer import _\\|from.*\\.py\\.writer import _" \
        src/knowledge_graph/builders/
must return nothing.
"""

from __future__ import annotations

import re
from pathlib import Path


_BUILDERS = Path(__file__).resolve().parents[2] / "src" / "knowledge_graph" / "builders"

# Match either ``from <...>.sv.writer import _foo`` or the py equivalent.
# We look for ``import _`` (leading underscore) because that's the
# private-name signature the refactor is closing off.
_PATTERN = re.compile(
    r"from\s+[\w.]*\.(?:sv|py)\.writer\s+import\s+\(?\s*_",
)


def test_no_cross_builder_private_imports() -> None:
    offenders: list[str] = []
    for path in _BUILDERS.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Also catch parenthesised multi-line imports: search the raw text.
        # Normalise newlines/whitespace inside parens so the regex can hit.
        flattened = re.sub(r"\(\s*", "(", text)
        if _PATTERN.search(flattened):
            offenders.append(str(path.relative_to(_BUILDERS.parent.parent.parent)))
    assert not offenders, (
        "Cross-builder private-name imports found (lift to _writer_common): "
        + ", ".join(offenders)
    )
