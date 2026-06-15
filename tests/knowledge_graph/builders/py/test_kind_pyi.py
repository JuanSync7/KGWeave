"""v1.6-#3 G6: ``.pyi`` stub files lift through the same walker.

The walker is content-only (libcst parses ``def stub(...) -> int: ...``
fine because the body is a valid Ellipsis statement). The facade
dispatch is by ``source="py"`` not file extension, so passing a
``.pyi`` path already routes through ``builders.py.extract``. This
test pins the contract so a future regression (extension filter, MIME
sniff, etc.) would be caught.
"""
from __future__ import annotations

from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "stub_module.pyi"


def test_walker_lifts_pyi_stub_definitions() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    kinds = {(n.kind, n.name) for n in nodes}
    assert ("PyFunction", "stubbed") in kinds
    assert ("PyClass", "StubClass") in kinds
    assert ("PyFunction", "method") in kinds


def test_extract_roundtrips_pyi_stub(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.kind IN"
            " ['PyFunction','PyClass'] RETURN n.name AS nm",
        )
        names = {row["nm"] for row in res.rows}
        assert {"stubbed", "StubClass", "method"}.issubset(names)
    finally:
        store.close()
