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
PKG = HERE / "fifo_pkg.sv"


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
