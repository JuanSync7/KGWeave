"""Tests for DPI-C scope-aware extraction.

Covers:
- extract_dpi_boundaries_with_scope: package, module, file-scope variants
- build_dpi_boundary_entities: imports_dpi edge emission
- backward-compat extract_dpi_boundaries wrapper
- real AES dataset file (skipped if absent)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kgweave.knowledge_graph.extraction.cpp_extractor import (
    build_dpi_boundary_entities,
    extract_dpi_boundaries,
    extract_dpi_boundaries_with_scope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_sv(tmp_path: Path, name: str, content: str) -> str:
    """Write a temporary .sv file and return its path string."""
    p = tmp_path / name
    p.write_text(content)
    return str(p)


# ---------------------------------------------------------------------------
# extract_dpi_boundaries_with_scope
# ---------------------------------------------------------------------------

def test_extract_dpi_boundaries_with_scope_returns_triples(tmp_path: Path) -> None:
    """Package-scoped import returns (scope_name, 'package', dpi_name)."""
    sv = _write_sv(
        tmp_path,
        "pkg.sv",
        'package foo;\n'
        '  import "DPI-C" function void bar();\n'
        'endpackage\n',
    )
    result = extract_dpi_boundaries_with_scope([sv])
    assert result == [("foo", "package", "bar")]


def test_module_scope_detected(tmp_path: Path) -> None:
    """Module-scoped import returns scope_kind='module'."""
    sv = _write_sv(
        tmp_path,
        "mod.sv",
        'module my_mod;\n'
        '  import "DPI-C" function int do_stuff();\n'
        'endmodule\n',
    )
    result = extract_dpi_boundaries_with_scope([sv])
    assert len(result) == 1
    scope_name, scope_kind, dpi_name = result[0]
    assert scope_name == "my_mod"
    assert scope_kind == "module"
    assert dpi_name == "do_stuff"


def test_file_scope_when_no_enclosing(tmp_path: Path) -> None:
    """DPI import outside any scope returns ('<file>', '<file>', name)."""
    sv = _write_sv(
        tmp_path,
        "bare.sv",
        '// No enclosing scope\n'
        'import "DPI-C" function void lone_fn();\n',
    )
    result = extract_dpi_boundaries_with_scope([sv])
    assert len(result) == 1
    scope_name, scope_kind, dpi_name = result[0]
    assert scope_name == "<file>"
    assert scope_kind == "<file>"
    assert dpi_name == "lone_fn"


def test_interface_scope_detected(tmp_path: Path) -> None:
    """Interface-scoped import returns scope_kind='interface'."""
    sv = _write_sv(
        tmp_path,
        "iface.sv",
        'interface my_if;\n'
        '  import "DPI-C" function void iface_fn();\n'
        'endinterface\n',
    )
    result = extract_dpi_boundaries_with_scope([sv])
    assert len(result) == 1
    assert result[0] == ("my_if", "interface", "iface_fn")


def test_scope_resets_after_endpackage(tmp_path: Path) -> None:
    """Scope resets to '<file>' after endpackage; subsequent import is file-scoped."""
    sv = _write_sv(
        tmp_path,
        "multi.sv",
        'package pkg_a;\n'
        '  import "DPI-C" function void fn_a();\n'
        'endpackage\n'
        'import "DPI-C" function void fn_b();\n',  # compilation-unit scope
    )
    result = extract_dpi_boundaries_with_scope([sv])
    assert ("pkg_a", "package", "fn_a") in result
    assert ("<file>", "<file>", "fn_b") in result


def test_multiple_imports_same_scope(tmp_path: Path) -> None:
    """Multiple DPI imports in the same package are all captured."""
    sv = _write_sv(
        tmp_path,
        "multi_pkg.sv",
        'package big_pkg;\n'
        '  import "DPI-C" function void f1();\n'
        '  import "DPI-C" function int  f2(int x);\n'
        '  import "DPI-C" context function void f3();\n'
        'endpackage\n',
    )
    result = extract_dpi_boundaries_with_scope([sv])
    names = [r[2] for r in result]
    assert set(names) == {"f1", "f2", "f3"}
    for scope_name, scope_kind, _ in result:
        assert scope_name == "big_pkg"
        assert scope_kind == "package"


# ---------------------------------------------------------------------------
# build_dpi_boundary_entities
# ---------------------------------------------------------------------------

def test_build_emits_imports_dpi_edges() -> None:
    """scoped_imports triggers imports_dpi triples with correct subject/object."""
    scoped = [
        ("pkg", "package", "fn1"),
        ("pkg", "package", "fn2"),
    ]
    result = build_dpi_boundary_entities(scoped_imports=scoped)
    triples = [t for t in result.triples if t.predicate == "imports_dpi"]
    assert len(triples) == 2
    subjects = {t.subject for t in triples}
    objects = {t.object for t in triples}
    assert subjects == {"pkg"}
    assert objects == {"fn1", "fn2"}


def test_build_emits_scope_entity_for_package() -> None:
    """A Package entity is created for a package-kind scope."""
    result = build_dpi_boundary_entities(
        scoped_imports=[("my_pkg", "package", "dpi_fn")]
    )
    entity_types = {e.name: e.type for e in result.entities}
    assert "my_pkg" in entity_types
    assert entity_types["my_pkg"] == "Package"


def test_build_emits_scope_entity_for_interface() -> None:
    """An Interface entity is created for an interface-kind scope."""
    result = build_dpi_boundary_entities(
        scoped_imports=[("my_if", "interface", "dpi_fn")]
    )
    entity_types = {e.name: e.type for e in result.entities}
    assert entity_types["my_if"] == "Interface"


def test_build_no_scope_entity_for_file_scope() -> None:
    """No scope entity is created when scope_kind is '<file>'."""
    result = build_dpi_boundary_entities(
        scoped_imports=[("<file>", "<file>", "dpi_fn")]
    )
    entity_names = {e.name for e in result.entities}
    assert "<file>" not in entity_names
    assert "dpi_fn" in entity_names


def test_build_layer_tag() -> None:
    """All emitted entities and triples carry layer='dpi_boundary'."""
    result = build_dpi_boundary_entities(
        scoped_imports=[("pkg", "package", "fn1")]
    )
    for e in result.entities:
        assert e.layer == "dpi_boundary", f"entity {e.name} has wrong layer"
    for t in result.triples:
        assert t.layer == "dpi_boundary", f"triple {t} has wrong layer"


def test_build_extractor_source_tag() -> None:
    """All emitted triples carry extractor_source='dpi_boundary'."""
    result = build_dpi_boundary_entities(
        scoped_imports=[("pkg", "package", "fn")]
    )
    for t in result.triples:
        assert t.extractor_source == "dpi_boundary"


def test_build_deduplicates_dpi_entities() -> None:
    """Repeated dpi_name across different scopes creates only one DPIBoundary."""
    result = build_dpi_boundary_entities(
        scoped_imports=[
            ("pkg_a", "package", "shared_fn"),
            ("pkg_b", "package", "shared_fn"),
        ]
    )
    dpi_entities = [e for e in result.entities if e.type == "DPIBoundary"]
    assert len(dpi_entities) == 1


# ---------------------------------------------------------------------------
# Backward-compat wrapper
# ---------------------------------------------------------------------------

def test_legacy_extract_dpi_boundaries_still_works(tmp_path: Path) -> None:
    """extract_dpi_boundaries returns a flat list of function names (no tuples)."""
    sv = _write_sv(
        tmp_path,
        "legacy.sv",
        'package p;\n'
        '  import "DPI-C" function void legacy_fn();\n'
        'endpackage\n',
    )
    result = extract_dpi_boundaries([sv])
    assert isinstance(result, list)
    assert all(isinstance(item, str) for item in result)
    assert "legacy_fn" in result


def test_legacy_wrapper_deduplicates(tmp_path: Path) -> None:
    """extract_dpi_boundaries deduplicates across files."""
    sv1 = _write_sv(tmp_path, "a.sv",
                    'package p1;\nimport "DPI-C" function void dup();\nendpackage\n')
    sv2 = _write_sv(tmp_path, "b.sv",
                    'package p2;\nimport "DPI-C" function void dup();\nendpackage\n')
    result = extract_dpi_boundaries([sv1, sv2])
    assert result.count("dup") == 1


def test_legacy_build_no_triples() -> None:
    """Legacy build_dpi_boundary_entities(dpi_names=[...]) emits no triples."""
    result = build_dpi_boundary_entities(dpi_names=["fn_a", "fn_b"])
    assert result.triples == []
    assert len(result.entities) == 2


# ---------------------------------------------------------------------------
# Real AES dataset
# ---------------------------------------------------------------------------

_AES_DPI_PKG = Path.home() / (
    "RagWeave/opentitan_data/hw/ip/aes/dv/aes_model_dpi/aes_model_dpi_pkg.sv"
)


@pytest.mark.skipif(
    not _AES_DPI_PKG.exists(),
    reason="OpenTitan AES dataset not available",
)
def test_aes_model_dpi_pkg_scope_real_file() -> None:
    """All 6 DPI-C imports in aes_model_dpi_pkg.sv come back with the correct scope."""
    result = extract_dpi_boundaries_with_scope([str(_AES_DPI_PKG)])
    assert len(result) >= 6, (
        f"Expected at least 6 DPI-C imports, got {len(result)}: {result}"
    )
    for scope_name, scope_kind, dpi_name in result:
        assert scope_name == "aes_model_dpi_pkg", (
            f"Unexpected scope {scope_name!r} for DPI import {dpi_name!r}"
        )
        assert scope_kind == "package", (
            f"Unexpected scope_kind {scope_kind!r} for {dpi_name!r}"
        )


# ---------------------------------------------------------------------------
# Structural-parser regression: complex return type (regex was blind to bit[7:0])
# ---------------------------------------------------------------------------

def test_dpi_import_with_packed_return_type(tmp_path: Path) -> None:
    """extract_dpi_boundaries_with_scope must capture DPI functions whose return
    type is a packed vector (e.g. ``bit[7:0]``).

    The old regex-based implementation used ``(?:[\\w:*&]+\\s+)?`` to skip the
    return type, which silently dropped any DPI function with a bracketed return
    type such as ``bit[7:0]``.  The pyslang-based replacement parses the SV AST
    and is immune to return-type syntax.
    """
    sv = _write_sv(
        tmp_path,
        "packed_ret.sv",
        'package packed_pkg;\n'
        '  import "DPI-C" function chandle fn_chandle();\n'
        '  import "DPI-C" function bit [7:0] fn_packed_byte();\n'
        'endpackage\n',
    )
    result = extract_dpi_boundaries_with_scope([sv])
    names = {r[2] for r in result}
    assert "fn_chandle" in names, f"fn_chandle missing from {names}"
    assert "fn_packed_byte" in names, (
        "fn_packed_byte with packed return type 'bit[7:0]' was not extracted — "
        "the extractor may still use a regex that drops bracketed return types"
    )
