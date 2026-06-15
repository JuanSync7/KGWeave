"""I7 — builder isolation.

Rows hand-written with ``source != 'sv'`` survive an SV re-extract intact:
their properties are unchanged, no edges connecting them are dropped, and
they are not deleted by the scoped-replacement logic.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from knowledge_graph.builders.sv import extract
from knowledge_graph.store import KGStore


SMALL_FIXTURES = ("fifo_pkg.sv", "fifo_if.sv")


@pytest.fixture()
def sv_fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "sv"


@pytest.fixture()
def small_corpus(tmp_path: Path, sv_fixture_dir: Path) -> list[Path]:
    dest = tmp_path / "corpus"
    dest.mkdir()
    out: list[Path] = []
    for name in SMALL_FIXTURES:
        dst = dest / name
        shutil.copyfile(sv_fixture_dir / name, dst)
        out.append(dst)
    return out


def _insert_probe_node(store, *, nid: str, payload: str) -> None:
    store.conn.execute(
        """
        CREATE (n:Node {
            id: $id, kind: 'ProbeKind', category: 'semantic', name: 'probe',
            source: 'probe', corpus: 'probe-corpus',
            origin_id: 'probe-origin',
            start_offset: 0, end_offset: 0,
            start_line: 0, end_line: 0, start_col: 0, end_col: 0,
            payload: $payload
        })
        """,
        {"id": nid, "payload": payload},
    )


def _read_node(store, nid: str) -> dict | None:
    res = store.conn.execute(
        """
        MATCH (n:Node {id: $id})
        RETURN n.kind, n.category, n.name, n.source, n.corpus,
               n.origin_id, n.payload
        """,
        {"id": nid},
    )
    if not res.has_next():
        return None
    row = res.get_next()
    return {
        "kind": row[0], "category": row[1], "name": row[2],
        "source": row[3], "corpus": row[4],
        "origin_id": row[5], "payload": row[6],
    }


def test_probe_node_survives_sv_reextract(tmp_path, small_corpus):
    """A hand-written non-SV node is unchanged after an SV extract runs."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    _insert_probe_node(store, nid="probe:n1", payload='{"hello":"world"}')
    before = _read_node(store, "probe:n1")
    assert before is not None
    assert before["source"] == "probe"

    extract(store, small_corpus, corpus="sv-corpus")

    after = _read_node(store, "probe:n1")
    assert after == before, f"probe node mutated: {before} -> {after}"


def test_probe_node_survives_repeat_reextract(tmp_path, small_corpus):
    """Repeated SV extracts (touch one file each time) never touch the probe."""
    store = KGStore.open(tmp_path / "kg.kuzu")
    _insert_probe_node(store, nid="probe:n2", payload='{"k":1}')
    before = _read_node(store, "probe:n2")

    extract(store, small_corpus, corpus="sv-corpus")
    # mutate one file & re-extract
    target = small_corpus[0]
    target.write_text(target.read_text() + "\n// poke\n")
    extract(store, small_corpus, corpus="sv-corpus")
    target.write_text(target.read_text() + "\n// poke again\n")
    extract(store, small_corpus, corpus="sv-corpus")

    after = _read_node(store, "probe:n2")
    assert after == before
