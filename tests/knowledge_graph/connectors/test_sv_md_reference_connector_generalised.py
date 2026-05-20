"""SvMarkdownReferenceConnector v1.3-#5 — generalised across SV identifier kinds.

The connector links MD inline-code / code-fence tokens to SV declarations
of the following kinds:

* module declarations
* package declarations
* typedef declarations (incl. forward typedefs)
* ANSI / non-ANSI port declarations (input/output/inout)

Tests use small synthetic fixtures rather than the full fifo corpus so each
scenario can isolate one or two name collisions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph import (
    BuilderConflict,
    SvMarkdownReferenceConnector,
    cypher,
    extract,
    open_store,
    register_connector,
    run_connectors,
)


@pytest.fixture(scope="module", autouse=True)
def _register_connector() -> None:
    try:
        register_connector(SvMarkdownReferenceConnector())
    except BuilderConflict:
        # Already registered by another module in this test session.
        pass


def _write(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


def _extract(
    store, *, source: str, corpus: str, files: list[Path]
) -> None:
    extract(store, source=source, corpus=corpus, paths=files)


def _refs_to(store, *, sv_name: str | None = None) -> int:
    if sv_name is None:
        res = cypher(
            store,
            """
            MATCH (m:Node)-[r:REFERENCES]->(s:Node)
            WHERE m.source = 'md' AND s.source = 'sv'
            RETURN count(r) AS k
            """,
        )
    else:
        res = cypher(
            store,
            """
            MATCH (m:Node)-[r:REFERENCES]->(s:Node)
            WHERE m.source = 'md' AND s.source = 'sv' AND s.name = $name
            RETURN count(r) AS k
            """,
            parameters={"name": sv_name},
        )
    row = res.rows[0]
    return int(next(iter(row.values())))


def _ref_targets_by_kind(store, *, sv_name: str) -> dict[str, int]:
    res = cypher(
        store,
        """
        MATCH (m:Node)-[r:REFERENCES]->(s:Node)
        WHERE m.source = 'md' AND s.source = 'sv' AND s.name = $name
        RETURN s.kind AS kind, count(r) AS k
        """,
        parameters={"name": sv_name},
    )
    return {row["kind"]: int(row["k"]) for row in res.rows}


def test_module_name_match_still_works(tmp_path: Path) -> None:
    sv = _write(tmp_path / "m.sv", "module my_mod (input logic clk); endmodule\n")
    md = _write(tmp_path / "n.md", "Refer to `my_mod`.\n")
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="c1", files=[sv])
    _extract(store, source="md", corpus="c1", files=[md])
    run_connectors(store, only=["sv-md-reference"])
    assert _refs_to(store, sv_name="my_mod") >= 1
    store.close()


def test_port_name_match(tmp_path: Path) -> None:
    sv = _write(
        tmp_path / "p.sv",
        "module m (input logic dbus_en, output logic ready_o); endmodule\n",
    )
    md = _write(tmp_path / "p.md", "Set the `dbus_en` strobe high.\n")
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="c1", files=[sv])
    _extract(store, source="md", corpus="c1", files=[md])
    run_connectors(store, only=["sv-md-reference"])
    assert _refs_to(store, sv_name="dbus_en") >= 1
    store.close()


def test_typedef_name_match(tmp_path: Path) -> None:
    sv = _write(
        tmp_path / "t.sv",
        "package pkg;\n"
        "  typedef logic [7:0] byte_t;\n"
        "endpackage\n",
    )
    md = _write(tmp_path / "t.md", "Use `byte_t` for data.\n")
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="c1", files=[sv])
    _extract(store, source="md", corpus="c1", files=[md])
    run_connectors(store, only=["sv-md-reference"])
    assert _refs_to(store, sv_name="byte_t") >= 1
    store.close()


def test_package_name_match(tmp_path: Path) -> None:
    sv = _write(
        tmp_path / "pk.sv",
        "package pkg_alpha;\n"
        "  typedef logic foo_t;\n"
        "endpackage\n",
    )
    md = _write(tmp_path / "pk.md", "Import from `pkg_alpha` first.\n")
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="c1", files=[sv])
    _extract(store, source="md", corpus="c1", files=[md])
    run_connectors(store, only=["sv-md-reference"])
    assert _refs_to(store, sv_name="pkg_alpha") >= 1
    store.close()


def test_collision_emits_edges_to_all_matches(tmp_path: Path) -> None:
    # Same name `bus` used both as a module and a typedef.
    sv = _write(
        tmp_path / "c.sv",
        "package p;\n"
        "  typedef logic [7:0] bus;\n"
        "endpackage\n"
        "module bus (input logic clk); endmodule\n",
    )
    md = _write(tmp_path / "c.md", "The `bus` name is overloaded.\n")
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="c1", files=[sv])
    _extract(store, source="md", corpus="c1", files=[md])
    run_connectors(store, only=["sv-md-reference"])
    targets = _ref_targets_by_kind(store, sv_name="bus")
    # Both the module and typedef SV nodes should receive an edge.
    assert "SyntaxKind.ModuleDeclaration" in targets
    assert "SyntaxKind.TypedefDeclaration" in targets
    # Edges carry ref_text == the matched name.
    res = cypher(
        store,
        """
        MATCH (m:Node)-[r:REFERENCES]->(s:Node)
        WHERE m.source = 'md' AND s.source = 'sv' AND s.name = 'bus'
        RETURN DISTINCT r.ref_text AS t
        """,
    )
    texts = {row["t"] for row in res.rows}
    assert texts == {"bus"}
    store.close()


def test_short_common_word_not_matched_unless_declared(tmp_path: Path) -> None:
    sv = _write(tmp_path / "k.sv", "module my_design; endmodule\n")
    # MD mentions `if` and `for` (SV keywords, not declarations) — must NOT emit edges.
    md = _write(tmp_path / "k.md", "Use `if` and `for` carefully.\n")
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="c1", files=[sv])
    _extract(store, source="md", corpus="c1", files=[md])
    run_connectors(store, only=["sv-md-reference"])
    assert _refs_to(store) == 0
    store.close()


def test_corpus_scoping_isolates_matches(tmp_path: Path) -> None:
    sv = _write(tmp_path / "a.sv", "module unique_mod; endmodule\n")
    md = _write(tmp_path / "b.md", "Mentions `unique_mod`.\n")
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="A", files=[sv])
    _extract(store, source="md", corpus="B", files=[md])  # different corpus
    run_connectors(store, only=["sv-md-reference"])
    assert _refs_to(store, sv_name="unique_mod") == 0
    store.close()


def test_empty_md_emits_zero(tmp_path: Path) -> None:
    sv = _write(tmp_path / "z.sv", "module zz; endmodule\n")
    md = _write(tmp_path / "z.md", "# Just prose, no spans.\n\nNo code here.\n")
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="c1", files=[sv])
    _extract(store, source="md", corpus="c1", files=[md])
    counts = run_connectors(store, only=["sv-md-reference"])
    assert counts["sv-md-reference"] == 0
    store.close()


def test_fence_body_matches_port_token(tmp_path: Path) -> None:
    sv = _write(
        tmp_path / "f.sv",
        "module top (input logic clk_i, output logic ready_o); endmodule\n",
    )
    md = _write(
        tmp_path / "f.md",
        "Connection example:\n\n"
        "```systemverilog\n"
        "assign ready_o = clk_i;\n"
        "```\n",
    )
    store = open_store(tmp_path / "kg.kuzu")
    _extract(store, source="sv", corpus="c1", files=[sv])
    _extract(store, source="md", corpus="c1", files=[md])
    run_connectors(store, only=["sv-md-reference"])
    assert _refs_to(store, sv_name="ready_o") >= 1
    assert _refs_to(store, sv_name="clk_i") >= 1
    store.close()
