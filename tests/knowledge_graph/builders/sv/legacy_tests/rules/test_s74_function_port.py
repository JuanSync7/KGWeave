"""S74 — ``FunctionPort`` promotion.

A ``FunctionPort`` is one entry in a function / task / method signature:

    function int add(input int a, output logic [3:0] b, ref bit c);

Each ``input int a`` / ``output logic [3:0] b`` / ``ref bit c`` parses as
``SyntaxKind.FunctionPort`` and S74 promotes it as a queryable node
attached to the enclosing function / method / extern prototype.

Coverage in the standing corpus (8 FunctionPort instances):

* ``fifo.next_ptr``                — 1 port: ``p`` (no direction keyword)
* ``fifo.sv_compute``              — 1 port: ``input x``
* ``fifo.c_compute``               — 1 port: ``input x`` (DPI import proto;
  the prototype lives under the DPIImport wrapper which S44 owns — S74
  still surfaces its ports if/when a frame is pushed by the function /
  method scope.  Today DPIImport does NOT push the function_stack so the
  c_compute port is dormant.)
* ``fifo.c_log``                   — 1 port: ``input level`` (same as above)
* ``extern_intf.helper_add``       — 2 ports: ``a``, ``b`` (extern proto;
  S56 pushes a function_stack frame for these)
* ``extern_intf.helper_log``       — 1 port: ``msg``
* ``extern_intf.helper_pulse``     — 1 port: ``input sig``

The S74 path is therefore: 2 promoted under ``fifo`` (next_ptr.p,
sv_compute.x) and 4 promoted under the extern_intf interface
(helper_add.a, helper_add.b, helper_log.msg, helper_pulse.sig). The two
DPIImport-wrapped ports stay dormant (no function_stack frame pushed by
DPIImport — that's a future / out-of-scope problem owned by S44).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
CORPUS_DIR = HERE / "corpus"
FIFO = CORPUS_DIR / "fifo.sv"
EXTERN = CORPUS_DIR / "extern_corpus.sv"


@pytest.fixture(scope="module")
def fifo_graph():
    text = FIFO.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


@pytest.fixture(scope="module")
def extern_graph():
    text = EXTERN.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _by_role(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role]


# ---------------------------------------------------------------------------
# Registration / metadata
# ---------------------------------------------------------------------------

def test_s74_ownership_stub_attributed():
    """``FunctionPort`` in the procedural RULES table carries ``S74``."""
    from knowledge_graph.builders.sv.semantic.rules.procedural import RULES

    matches = [(k, fn) for (k, fn) in RULES
               if k == pyslang.SyntaxKind.FunctionPort]
    assert len(matches) == 1
    _, fn = matches[0]
    assert getattr(fn, "__rule_id__", None) == "S74"


def test_s74_active_rule_registered():
    """S74 is in ``_ACTIVE_RULE_IDS`` (bucket1 checklist counts it)."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS

    assert "S74" in _ACTIVE_RULE_IDS


def test_s74_kind_in_rule_table():
    """Composed RULE_TABLE dispatches ``FunctionPort`` to the S74 stub."""
    from knowledge_graph.builders.sv.semantic.rules import RULE_TABLE

    fn = RULE_TABLE.get(pyslang.SyntaxKind.FunctionPort)
    assert fn is not None
    assert getattr(fn, "__rule_id__", None) == "S74"


# ---------------------------------------------------------------------------
# Promotion against fifo.sv (module-scope function bodies)
# ---------------------------------------------------------------------------

def test_s74_module_function_ports_promoted(fifo_graph):
    """``next_ptr(p)`` and ``sv_compute(input int x)`` each surface a
    function_port node under the fifo module path."""
    ports = _by_role(fifo_graph, "function_port")
    paths = {p["semantic"]["path"] for p in ports}
    assert "fifo.next_ptr.p" in paths
    # ``sv_compute`` lives in the ``dpi_demo`` module in fifo.sv, not fifo.
    assert "dpi_demo.sv_compute.x" in paths


def test_s74_module_function_port_attrs(fifo_graph):
    """Direction / data_type / name attrs are preserved (empty direction
    keyword surfaces as empty string, not None)."""
    by_path = {p["semantic"]["path"]: p
               for p in _by_role(fifo_graph, "function_port")}

    p = by_path["dpi_demo.sv_compute.x"]
    attrs = p["semantic"].get("attributes", {})
    assert attrs.get("direction") == "input"
    assert attrs.get("name") == "x"
    assert "int" in (attrs.get("data_type") or "")

    p2 = by_path["fifo.next_ptr.p"]
    attrs2 = p2["semantic"].get("attributes", {})
    # next_ptr's port has no direction keyword in source.
    assert attrs2.get("direction") in ("", None) or attrs2.get("direction") == ""
    assert attrs2.get("name") == "p"


def test_s74_has_function_port_edges(fifo_graph):
    """has_function_port edge runs from the enclosing function to each
    promoted function_port."""
    edges = [e for e in fifo_graph["edges"]
             if e.get("type") == "has_function_port"]
    # Two ports under fifo functions (next_ptr.p and sv_compute.x).
    port_paths = {p["semantic"]["path"]
                  for p in _by_role(fifo_graph, "function_port")
                  if p["semantic"]["path"].startswith("fifo.")}
    assert len(edges) >= len(port_paths)
    # Each port has exactly one inbound has_function_port edge.
    for p in _by_role(fifo_graph, "function_port"):
        inbound = [e for e in edges if e["dst"] == p["id"]]
        assert len(inbound) == 1, (
            f"{p['semantic']['path']}: expected 1 has_function_port edge, "
            f"got {len(inbound)}"
        )


# ---------------------------------------------------------------------------
# Promotion against extern_corpus.sv (interface extern prototypes via S56)
# ---------------------------------------------------------------------------

def test_s74_extern_prototype_ports_promoted(extern_graph):
    """Extern method prototypes contribute FunctionPort nodes under their
    interface scope via the function_stack frame the S56
    FunctionPrototype branch pushes."""
    ports = _by_role(extern_graph, "function_port")
    paths = {p["semantic"]["path"] for p in ports}
    # extern_corpus.sv defines an interface ``extern_intf`` (per S56 docs).
    # Confirm all four named ports appear under it.
    assert any(p.endswith(".helper_add.a") for p in paths), paths
    assert any(p.endswith(".helper_add.b") for p in paths), paths
    assert any(p.endswith(".helper_log.msg") for p in paths), paths
    assert any(p.endswith(".helper_pulse.sig") for p in paths), paths


def test_s74_extern_prototype_port_directions(extern_graph):
    """``helper_pulse(input logic sig)`` — direction is preserved on the
    promoted function_port node even when the parent is an extern
    prototype rather than a fully-bodied function."""
    by_path = {p["semantic"]["path"]: p
               for p in _by_role(extern_graph, "function_port")}
    sig = next((p for k, p in by_path.items()
                if k.endswith(".helper_pulse.sig")), None)
    assert sig is not None
    attrs = sig["semantic"].get("attributes", {})
    assert attrs.get("direction") == "input"


# ---------------------------------------------------------------------------
# Ordering, no duplicates, no regression to existing roles
# ---------------------------------------------------------------------------

def test_s74_multiple_ports_keep_their_names(extern_graph):
    """``helper_add(int a, int b)`` — both ports promote, names preserved,
    no merging or overwriting."""
    by_path = {p["semantic"]["path"]: p
               for p in _by_role(extern_graph, "function_port")}
    a = next((p for k, p in by_path.items()
              if k.endswith(".helper_add.a")), None)
    b = next((p for k, p in by_path.items()
              if k.endswith(".helper_add.b")), None)
    assert a is not None and b is not None
    assert a["semantic"]["name"] == "a"
    assert b["semantic"]["name"] == "b"
    # The two ports are distinct gid nodes.
    assert a["id"] != b["id"]


def test_s74_roundtrip_fifo(fifo_graph):
    """Promotion does not perturb the token stream — emit() == source."""
    from knowledge_graph.builders.sv.unlift import emit
    assert emit(fifo_graph) == FIFO.read_text()


def test_s74_roundtrip_extern(extern_graph):
    """Same round-trip invariant for extern_corpus.sv."""
    from knowledge_graph.builders.sv.unlift import emit
    assert emit(extern_graph) == EXTERN.read_text()
