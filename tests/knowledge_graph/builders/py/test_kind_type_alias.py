"""v1.6-#3 G3: PEP 695 ``type X = ...`` aliases as PyTypeAlias kind."""
from __future__ import annotations

from pathlib import Path

from knowledge_graph import cypher, extract, open_store

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "py"
FIXTURE = FIXTURE_DIR / "type_aliases.py"


def test_walker_lifts_pep695_type_aliases() -> None:
    from knowledge_graph.builders.py.walker import lift_python

    nodes = lift_python(FIXTURE.read_bytes())
    aliases = {n.name for n in nodes if n.kind == "PyTypeAlias"}
    assert aliases == {"Vector", "IntList"}


def test_writer_roundtrips_type_alias_kind(tmp_path: Path) -> None:
    store = open_store(tmp_path / "kg.kuzu")
    try:
        extract(store, source="py", corpus="demo", paths=[FIXTURE])
        res = cypher(
            store,
            "MATCH (n:Node) WHERE n.source='py' AND n.kind='PyTypeAlias'"
            " RETURN n.name AS nm",
        )
        assert {row["nm"] for row in res.rows} == {"Vector", "IntList"}
    finally:
        store.close()
