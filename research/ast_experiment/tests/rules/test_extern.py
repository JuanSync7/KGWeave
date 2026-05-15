"""S29: Extern module/interface/program declaration promotion.

The corpus ``extern_corpus.sv`` declares three extern headers — one each of
``extern module``, ``extern interface``, ``extern program`` — followed by
the full bodies of the same three constructs. S29 promotes:

* The three ExternModuleDeclSyntax nodes → role=extern_decl with
  attributes["kind"] ∈ {"module", "interface", "program"}. All three live
  at compilation-unit scope (root-anchored, no enclosing parent).
* The ``declares`` edge from each extern decl to the matching full
  declaration via the shared semantic name index (S1 registers the full
  module / interface under the bare name).
* The ports attribute carries the port-name list from the header.

The full module / interface / program declarations are promoted by S1
(modules / interfaces / packages); the program body itself is promoted
by S30, which is intentionally out of scope here — S29 only owns the
extern headers.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
EXT = HERE / "corpus" / "extern_corpus.sv"


@pytest.fixture(scope="module")
def ext_graph():
    text = EXT.read_text()
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


def test_s29_extern_decls_promoted(ext_graph):
    """All three extern decls (module / interface / program) appear as
    role=extern_decl nodes at compilation-unit scope."""
    externs = _by_role(ext_graph, "extern_decl")
    assert len(externs) == 3
    by_name = {n["semantic"]["name"]: n for n in externs}
    assert set(by_name) == {"ext_mod", "ext_if", "ext_prog"}
    # cu-scope: path equals the bare declared name.
    for name, node in by_name.items():
        assert node["semantic"]["path"] == name


def test_s29_extern_kind_attribute(ext_graph):
    """The ``kind`` attribute discriminates the three header variants."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    assert externs["ext_mod"]["semantic"]["attributes"]["kind"] == "module"
    assert externs["ext_if"]["semantic"]["attributes"]["kind"] == "interface"
    assert externs["ext_prog"]["semantic"]["attributes"]["kind"] == "program"


def test_s29_extern_port_list(ext_graph):
    """The port-name list is extracted structurally from the header."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    # extern module ext_mod (... clk, q)
    assert externs["ext_mod"]["semantic"]["attributes"]["ports"] == ["clk", "q"]
    # extern interface ext_if (... clk)
    assert externs["ext_if"]["semantic"]["attributes"]["ports"] == ["clk"]
    # extern program ext_prog ()
    assert externs["ext_prog"]["semantic"]["attributes"]["ports"] == []


def test_s29_declares_edge_resolves_module(ext_graph):
    """The ``ext_mod`` extern decl has a ``declares`` edge pointing to the
    full module declaration resolved via the shared name index."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    modules = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "module")}
    assert "ext_mod" in modules, "full module ext_mod must be promoted by S1"
    ext_id = externs["ext_mod"]["id"]
    mod_id = modules["ext_mod"]["id"]
    edges = [e for e in ext_graph["edges"]
             if e["type"] == "declares"
             and e["src"] == ext_id
             and e["dst"] == mod_id]
    assert len(edges) == 1, f"expected 1 declares edge, got {len(edges)}"


def test_s29_declares_edge_resolves_interface(ext_graph):
    """The ``ext_if`` extern decl has a ``declares`` edge to the full
    interface declaration."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    interfaces = {n["semantic"]["name"]: n
                  for n in _by_role(ext_graph, "interface")}
    assert "ext_if" in interfaces, "full interface ext_if must be promoted by S1"
    ext_id = externs["ext_if"]["id"]
    if_id = interfaces["ext_if"]["id"]
    edges = [e for e in ext_graph["edges"]
             if e["type"] == "declares"
             and e["src"] == ext_id
             and e["dst"] == if_id]
    assert len(edges) == 1


def test_s29_no_has_extern_decl_at_cu_scope(ext_graph):
    """At compilation-unit scope the extern decls are root-anchored — no
    ``has_extern_decl`` containment edge should be emitted."""
    edges = [e for e in ext_graph["edges"] if e["type"] == "has_extern_decl"]
    assert edges == [], (
        f"cu-scope extern decls must not emit has_extern_decl; got {edges}"
    )


# ---------------------------------------------------------------------------
# S30 — Full ProgramDeclaration body promotion
# ---------------------------------------------------------------------------


def test_s30_program_body_promoted(ext_graph):
    """The full ``program ext_prog ();`` body is promoted as role=program
    (NOT role=module — pyslang reuses ModuleDeclarationSyntax across all
    four ModuleDeclaration variants, so the kind discriminator must route
    program bodies to a distinct role)."""
    programs = _by_role(ext_graph, "program")
    assert len(programs) == 1, (
        f"expected 1 program node, got {len(programs)}"
    )
    prog = programs[0]
    assert prog["semantic"]["name"] == "ext_prog"
    # cu-scope program: path is the bare name (no parent prefix).
    assert prog["semantic"]["path"] == "ext_prog"


def test_s30_program_not_double_promoted_as_module(ext_graph):
    """The program body must not also surface as role=module — the kind
    discriminator in the shared ModuleDeclarationSyntax branch must
    produce exactly one role per declaration."""
    module_names = {n["semantic"]["name"]
                    for n in _by_role(ext_graph, "module")}
    assert "ext_prog" not in module_names, (
        "ext_prog must be promoted as role=program, not role=module"
    )


def test_s30_program_port_list(ext_graph):
    """The program body's port-name list is extracted from the
    ProgramHeader. ``program ext_prog ();`` has an empty port list."""
    programs = {n["semantic"]["name"]: n
                for n in _by_role(ext_graph, "program")}
    assert programs["ext_prog"]["semantic"]["attributes"]["ports"] == []


def test_s30_program_name_index_entry(ext_graph):
    """The program is registered in the shared name index under the bare
    name and under the ``program:`` prefix, mirroring how S1 registers
    modules (``module:``) and interfaces (``interface:``)."""
    idx = ext_graph["semantic_name_index"]
    programs = {n["semantic"]["name"]: n
                for n in _by_role(ext_graph, "program")}
    prog_gid = programs["ext_prog"]["id"]
    assert idx.get("ext_prog") == prog_gid
    assert idx.get("program:ext_prog") == prog_gid


def test_s30_no_has_program_at_cu_scope(ext_graph):
    """The corpus has only a cu-scope program; ``has_program`` is only
    emitted for nested programs (rare and LRM-non-conformant), so the
    edge list must be empty for this corpus."""
    edges = [e for e in ext_graph["edges"] if e["type"] == "has_program"]
    assert edges == [], (
        f"cu-scope programs must not emit has_program; got {edges}"
    )


def test_s30_extern_program_declares_full_program(ext_graph):
    """The S29 ``declares`` edge from ``extern program ext_prog`` should
    target the S30-promoted full program body — i.e. cross-cuts the
    extern/full pair via the shared name index, the same way S29 wires
    extern module → full module."""
    externs = {n["semantic"]["name"]: n
               for n in _by_role(ext_graph, "extern_decl")}
    programs = {n["semantic"]["name"]: n
                for n in _by_role(ext_graph, "program")}
    ext_id = externs["ext_prog"]["id"]
    prog_id = programs["ext_prog"]["id"]
    edges = [e for e in ext_graph["edges"]
             if e["type"] == "declares"
             and e["src"] == ext_id
             and e["dst"] == prog_id]
    assert len(edges) == 1, (
        f"expected extern program → full program declares edge, got "
        f"{len(edges)}"
    )


# ---------------------------------------------------------------------------
# S44 — DPIImport promotion
# ---------------------------------------------------------------------------

FIFO = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def fifo_graph():
    """Graph built from fifo.sv — contains the S44 dpi_demo module."""
    text = FIFO.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def test_s44_dpi_imports_promoted(fifo_graph):
    """All three DPI import declarations inside ``dpi_demo`` are promoted as
    role=dpi_import nodes."""
    imports = _by_role(fifo_graph, "dpi_import")
    by_name = {n["semantic"]["name"]: n for n in imports}
    assert "c_compute" in by_name, f"c_compute missing; found {set(by_name)}"
    assert "c_log" in by_name, f"c_log missing; found {set(by_name)}"
    assert "dpi_reset" in by_name, f"dpi_reset missing; found {set(by_name)}"


def test_s44_path_key_includes_scope(fifo_graph):
    """Path key is ``<scope>.<function_name>`` — the enclosing module name
    is included as a prefix."""
    imports = {n["semantic"]["name"]: n
               for n in _by_role(fifo_graph, "dpi_import")}
    assert imports["c_compute"]["semantic"]["path"] == "dpi_demo.c_compute"
    assert imports["c_log"]["semantic"]["path"] == "dpi_demo.c_log"
    assert imports["dpi_reset"]["semantic"]["path"] == "dpi_demo.dpi_reset"


def test_s44_spec_attribute(fifo_graph):
    """The ``spec`` attribute records the DPI string literal ("DPI-C" or
    "DPI") stripped of surrounding quotes."""
    imports = {n["semantic"]["name"]: n
               for n in _by_role(fifo_graph, "dpi_import")}
    assert imports["c_compute"]["semantic"]["attributes"]["spec"] == "DPI-C"
    assert imports["c_log"]["semantic"]["attributes"]["spec"] == "DPI-C"
    assert imports["dpi_reset"]["semantic"]["attributes"]["spec"] == "DPI"


def test_s44_import_kind_attribute(fifo_graph):
    """The ``import_kind`` attribute distinguishes function from task."""
    imports = {n["semantic"]["name"]: n
               for n in _by_role(fifo_graph, "dpi_import")}
    assert imports["c_compute"]["semantic"]["attributes"]["import_kind"] == "function"
    assert imports["c_log"]["semantic"]["attributes"]["import_kind"] == "task"
    assert imports["dpi_reset"]["semantic"]["attributes"]["import_kind"] == "function"


def test_s44_has_dpi_import_edge(fifo_graph):
    """Each DPI import node is connected to the enclosing module via a
    ``has_dpi_import`` edge."""
    imports = _by_role(fifo_graph, "dpi_import")
    import_ids = {n["id"] for n in imports}
    dpi_edges = [e for e in fifo_graph["edges"]
                 if e["type"] == "has_dpi_import"]
    edge_dsts = {e["dst"] for e in dpi_edges}
    assert import_ids == edge_dsts, (
        f"has_dpi_import edge destinations {edge_dsts} must match "
        f"all dpi_import node ids {import_ids}"
    )


def test_s44_name_index_registered(fifo_graph):
    """Every DPI import is registered in the shared name index under the
    qualified path ``dpi_demo.<function_name>``."""
    idx = fifo_graph["semantic_name_index"]
    imports = {n["semantic"]["name"]: n
               for n in _by_role(fifo_graph, "dpi_import")}
    for name, node in imports.items():
        path = f"dpi_demo.{name}"
        assert idx.get(path) == node["id"], (
            f"name_index[{path!r}] expected {node['id']!r}, "
            f"got {idx.get(path)!r}"
        )


def test_s44_roundtrip(fifo_graph):
    """Byte-equal round-trip: lift → emit must reconstruct the exact source
    bytes from fifo.sv (which now contains the dpi_demo module).  The
    semantic layer only mutates ``node["semantic"]`` and appends edges — it
    never touches ``node["tokens"]`` or ``node["children"]``, so the emit
    pass must reproduce the original text unchanged."""
    from research.ast_experiment.src.unlift import emit
    text = FIFO.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    graph_fresh = __import__(
        "research.ast_experiment.src.lift", fromlist=["lift"]
    ).lift(tree)
    reconstructed = emit(graph_fresh)
    assert reconstructed == text, (
        f"round-trip mismatch on fifo.sv after S44 corpus addition"
    )


# ---------------------------------------------------------------------------
# S45 — DPIExport edge-only promotion
# ---------------------------------------------------------------------------


def test_s45_dpi_exports_edge_resolved(fifo_graph):
    """The ``export "DPI-C" function sv_compute;`` declaration emits a
    ``dpi_exports`` edge from the ``dpi_demo`` module to the ``sv_compute``
    function node.  The target is resolved via name_index (``dpi_demo.sv_compute``
    is registered by S10 because sv_compute is a regular SV function)."""
    funcs = {n["semantic"]["name"]: n
             for n in _by_role(fifo_graph, "function")}
    modules = {n["semantic"]["name"]: n
               for n in _by_role(fifo_graph, "module")}
    assert "sv_compute" in funcs, (
        f"sv_compute function must be promoted by S10; found: {set(funcs)}"
    )
    assert "dpi_demo" in modules, "dpi_demo module must be promoted"
    mod_id = modules["dpi_demo"]["id"]
    fn_id = funcs["sv_compute"]["id"]
    edges = [e for e in fifo_graph["edges"]
             if e["type"] == "dpi_exports"
             and e["src"] == mod_id
             and e["dst"] == fn_id]
    assert len(edges) == 1, (
        f"expected 1 dpi_exports edge dpi_demo->sv_compute, got {len(edges)}"
    )


def test_s45_dpi_exports_payload_resolved(fifo_graph):
    """The resolved ``dpi_exports`` edge carries spec=DPI-C, export_kind=function
    in its payload."""
    funcs = {n["semantic"]["name"]: n
             for n in _by_role(fifo_graph, "function")}
    modules = {n["semantic"]["name"]: n
               for n in _by_role(fifo_graph, "module")}
    mod_id = modules["dpi_demo"]["id"]
    fn_id = funcs["sv_compute"]["id"]
    edge = next(
        e for e in fifo_graph["edges"]
        if e["type"] == "dpi_exports"
        and e["src"] == mod_id
        and e["dst"] == fn_id
    )
    assert edge["payload"]["spec"] == "DPI-C", (
        f"expected spec='DPI-C', got {edge['payload']['spec']!r}"
    )
    assert edge["payload"]["export_kind"] == "function", (
        f"expected export_kind='function', got {edge['payload']['export_kind']!r}"
    )


def test_s45_dpi_exports_edge_unresolved(fifo_graph):
    """The ``export "DPI-C" task sv_task;`` declaration — where sv_task has no
    body in this scope — emits a ``dpi_exports`` edge with
    ``dst="_unresolved.sv_task"`` and ``payload["unresolved"]=True``."""
    modules = {n["semantic"]["name"]: n
               for n in _by_role(fifo_graph, "module")}
    mod_id = modules["dpi_demo"]["id"]
    edges = [e for e in fifo_graph["edges"]
             if e["type"] == "dpi_exports"
             and e["src"] == mod_id
             and e["dst"] == "_unresolved.sv_task"]
    assert len(edges) == 1, (
        f"expected 1 unresolved dpi_exports edge for sv_task, got {len(edges)}"
    )
    assert edges[0]["payload"].get("unresolved") is True


def test_s45_dpi_exports_unresolved_payload(fifo_graph):
    """The unresolved ``dpi_exports`` edge carries spec=DPI-C, export_kind=task
    and unresolved=True in its payload."""
    modules = {n["semantic"]["name"]: n
               for n in _by_role(fifo_graph, "module")}
    mod_id = modules["dpi_demo"]["id"]
    edge = next(
        e for e in fifo_graph["edges"]
        if e["type"] == "dpi_exports"
        and e["src"] == mod_id
        and e["dst"] == "_unresolved.sv_task"
    )
    assert edge["payload"]["spec"] == "DPI-C"
    assert edge["payload"]["export_kind"] == "task"
    assert edge["payload"]["unresolved"] is True


def test_s45_no_new_node_created(fifo_graph):
    """S45 is edge-only: the DPIExport declaration must NOT produce a new
    semantic node with a ``dpi_export`` role.  The SyntaxKind is a
    relationship-only directive — all semantic content lives on the edge."""
    dpi_export_nodes = [n for n in fifo_graph["nodes"]
                        if n.get("semantic", {}).get("role") == "dpi_export"]
    assert dpi_export_nodes == [], (
        f"S45 must be edge-only; found unexpected dpi_export nodes: "
        f"{dpi_export_nodes}"
    )


def test_s45_roundtrip(fifo_graph):
    """Byte-equal round-trip after S45 corpus additions.  The semantic layer
    only mutates ``node["semantic"]`` and appends edges — the emit pass must
    reproduce the original fifo.sv bytes unchanged."""
    from research.ast_experiment.src.unlift import emit
    text = FIFO.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    graph_fresh = __import__(
        "research.ast_experiment.src.lift", fromlist=["lift"]
    ).lift(tree)
    reconstructed = emit(graph_fresh)
    assert reconstructed == text, (
        f"round-trip mismatch on fifo.sv after S45 corpus addition"
    )
