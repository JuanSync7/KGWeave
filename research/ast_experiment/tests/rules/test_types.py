"""S31: struct/union typedef enrichment + ForwardTypedefDeclaration promotion.

The corpus ``fifo_pkg.sv`` exercises four typedef variants under
``package fifo_pkg``:

* ``fifo_status_e`` — ``typedef enum ...`` (S9c, kept passing here for
  regression coverage).
* ``fifo_word_t`` — ``typedef struct packed { ... } ...`` (S31 struct body).
* ``fifo_iu_t`` — ``typedef union { ... } ...`` (S31 union body).
* ``fifo_fwd_t`` — ``typedef fifo_fwd_t;`` bare forward declaration (S31
  ForwardTypedefDeclaration → role=typedef_forward).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
PKG = HERE / "corpus" / "fifo_pkg.sv"
FIFO = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def multi_graph(tmp_path_factory):
    """fifo_pkg.sv + fifo.sv promoted into a single shared graph via the
    production build_kg path (mirrors tests/queries/test_multi.py)."""
    from research.ast_experiment.src.build import build_kg

    graph, _trees, _comp = build_kg([PKG, FIFO])
    return graph


def _build_inline_graph(*sv_texts):
    """Build a promoted graph from raw SV source strings by writing them to
    temp files and routing through build_kg — keeps multi-file resolution
    identical to production."""
    import tempfile

    from research.ast_experiment.src.build import build_kg

    tmpdir = Path(tempfile.mkdtemp(prefix="s32_"))
    paths = []
    for i, txt in enumerate(sv_texts):
        p = tmpdir / f"file_{i}.sv"
        p.write_text(txt)
        paths.append(p)
    graph, _trees, _comp = build_kg(paths)
    return graph


@pytest.fixture(scope="module")
def pkg_graph():
    text = PKG.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _by_role(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role]


def _by_path(graph, path):
    for n in graph["nodes"]:
        sem = n.get("semantic", {})
        if sem.get("path") == path:
            return n
    return None


def test_s31_existing_enum_typedef_regression(pkg_graph):
    """S9c regression: the enum-bodied typedef still surfaces as role=typedef
    and its enum value declarators are still promoted."""
    td = _by_path(pkg_graph, "fifo_pkg.fifo_status_e")
    assert td is not None
    assert td["semantic"]["role"] == "typedef"
    # Enum values still attached.
    evs = [
        e for e in pkg_graph["edges"]
        if e["src"] == td["id"] and e["type"] == "has_enum_value"
    ]
    assert len(evs) == 3


def test_s31_struct_typedef_body_kind(pkg_graph):
    """The struct-bodied typedef carries body_kind=struct + packed=True."""
    td = _by_path(pkg_graph, "fifo_pkg.fifo_word_t")
    assert td is not None and td["semantic"]["role"] == "typedef"
    attrs = td["semantic"]["attributes"]
    assert attrs["body_kind"] == "struct"
    assert attrs["packed"] is True
    assert attrs["tagged"] is False


def test_s31_struct_members_extracted(pkg_graph):
    """The members list captures all declarators with their type_text."""
    td = _by_path(pkg_graph, "fifo_pkg.fifo_word_t")
    members = td["semantic"]["attributes"]["members"]
    names = [m["name"] for m in members]
    assert names == ["cmd", "payload"]
    # Type text is non-empty and includes the integral keyword.
    assert all("logic" in m["type_text"] for m in members)


def test_s31_union_typedef_body_kind(pkg_graph):
    """The union-bodied typedef carries body_kind=union + packed=False."""
    td = _by_path(pkg_graph, "fifo_pkg.fifo_iu_t")
    assert td is not None
    attrs = td["semantic"]["attributes"]
    assert attrs["body_kind"] == "union"
    assert attrs["packed"] is False
    assert attrs["tagged"] is False
    names = [m["name"] for m in attrs["members"]]
    assert names == ["i", "b"]


def test_s31_struct_members_are_not_enum_values(pkg_graph):
    """Struct declarators (cmd / payload) must NOT promote as enum values
    under the struct typedef — that would be the legacy S9c behaviour.
    """
    td = _by_path(pkg_graph, "fifo_pkg.fifo_word_t")
    evs = [
        e for e in pkg_graph["edges"]
        if e["src"] == td["id"] and e["type"] == "has_enum_value"
    ]
    assert evs == []


def test_s31_forward_typedef_node(pkg_graph):
    """The bare ``typedef fifo_fwd_t;`` forward declaration becomes its own
    role=typedef_forward node under fifo_pkg with forward=True."""
    fwd = _by_path(pkg_graph, "fifo_pkg.fifo_fwd_t")
    assert fwd is not None
    sem = fwd["semantic"]
    assert sem["role"] == "typedef_forward"
    assert sem["name"] == "fifo_fwd_t"
    assert sem["attributes"]["forward"] is True


def test_s31_forward_typedef_edge(pkg_graph):
    """The forward decl is attached to fifo_pkg by a ``has_typedef`` edge so
    package-level typedef queries return both full and forward decls."""
    pkg = _by_path(pkg_graph, "fifo_pkg")
    fwd = _by_path(pkg_graph, "fifo_pkg.fifo_fwd_t")
    assert any(
        e["src"] == pkg["id"] and e["dst"] == fwd["id"]
        and e["type"] == "has_typedef"
        for e in pkg_graph["edges"]
    )


# ---------------------------------------------------------------------------
# S32: PackageImport / PackageExport declarations
# ---------------------------------------------------------------------------


def test_s32_wildcard_import_edge_from_fifo(multi_graph):
    """The header-form ``import fifo_pkg::*;`` on the ``fifo`` module emits
    an ``imports`` edge from the fifo module node to the fifo_pkg package
    node with payload item=="*"."""
    fifo = _by_path(multi_graph, "fifo")
    pkg = _by_path(multi_graph, "fifo_pkg")
    assert fifo is not None and pkg is not None
    matches = [
        e for e in multi_graph["edges"]
        if e["src"] == fifo["id"] and e["dst"] == pkg["id"]
        and e["type"] == "imports"
        and e["payload"].get("item") == "*"
    ]
    assert len(matches) == 1, f"expected exactly one wildcard imports edge, got {matches}"
    assert matches[0]["payload"].get("package") == "fifo_pkg"
    assert matches[0]["payload"].get("unresolved") is not True


def test_s32_explicit_item_import_edge_from_fifo(multi_graph):
    """The body-form ``import fifo_pkg::FULL;`` emits a second ``imports``
    edge with payload item==\"FULL\"."""
    fifo = _by_path(multi_graph, "fifo")
    pkg = _by_path(multi_graph, "fifo_pkg")
    matches = [
        e for e in multi_graph["edges"]
        if e["src"] == fifo["id"] and e["dst"] == pkg["id"]
        and e["type"] == "imports"
        and e["payload"].get("item") == "FULL"
    ]
    assert len(matches) == 1


def test_s32_multi_item_import_fans_out():
    """One ``import a_pkg::A, a_pkg::B;`` produces TWO ``imports`` edges,
    one per item."""
    graph = _build_inline_graph(
        "package a_pkg;\n  parameter int A = 1;\n  parameter int B = 2;\nendpackage\n",
        "module m;\n  import a_pkg::A, a_pkg::B;\nendmodule\n",
    )
    m = _by_path(graph, "m")
    pkg = _by_path(graph, "a_pkg")
    edges = [
        e for e in graph["edges"]
        if e["src"] == m["id"] and e["dst"] == pkg["id"]
        and e["type"] == "imports"
    ]
    items = sorted(e["payload"].get("item") for e in edges)
    assert items == ["A", "B"]


def test_s32_export_emits_exports_edge():
    """A package that re-exports another package emits an ``exports`` edge
    from the re-exporting package to the original package."""
    graph = _build_inline_graph(
        "package base_pkg;\n  parameter int X = 1;\nendpackage\n",
        "package wrap_pkg;\n  import base_pkg::*;\n  export base_pkg::*;\nendpackage\n",
    )
    wrap = _by_path(graph, "wrap_pkg")
    base = _by_path(graph, "base_pkg")
    exports = [
        e for e in graph["edges"]
        if e["src"] == wrap["id"] and e["dst"] == base["id"]
        and e["type"] == "exports" and e["payload"].get("item") == "*"
    ]
    assert len(exports) == 1
    assert exports[0]["payload"].get("unresolved") is not True


def test_s32_unresolved_external_package():
    """An import from a package that is NOT in the name index points the
    edge at the synthetic ``_unresolved.<pkg>`` placeholder with
    payload[\"unresolved\"]=True."""
    graph = _build_inline_graph(
        "module m;\n  import nowhere_pkg::*;\nendmodule\n",
    )
    m = _by_path(graph, "m")
    edges = [
        e for e in graph["edges"]
        if e["src"] == m["id"] and e["type"] == "imports"
        and e["payload"].get("package") == "nowhere_pkg"
    ]
    assert len(edges) == 1
    assert edges[0]["dst"] == "_unresolved.nowhere_pkg"
    assert edges[0]["payload"].get("unresolved") is True
