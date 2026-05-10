# @summary
# Tests for SWTestExtractor.
# Covers: SW_Test entity emission, accesses_csr from mmio patterns,
# tests_module from filename matching, and round-trip to backend.
# @end-summary
"""Tests for SWTestExtractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.extraction.sw_test_extractor import (
    SWTestExtractor,
    SW_TEST_SOURCE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.write_text(content)


def _entity_names(result, type_filter=None):
    if type_filter:
        return {e.name for e in result.entities if e.type == type_filter}
    return {e.name for e in result.entities}


def _triples(result, predicate=None, subject=None):
    triples = result.triples
    if predicate:
        triples = [t for t in triples if t.predicate == predicate]
    if subject:
        triples = [t for t in triples if t.subject == subject]
    return triples


# ---------------------------------------------------------------------------
# test_sw_test_entity_emitted
# ---------------------------------------------------------------------------


def test_sw_test_entity_emitted(tmp_path):
    _write(tmp_path / "aes_smoketest.c", "// bare test\nvoid test_main(void) {}\n")
    extractor = SWTestExtractor(known_entity_names=["aes"])
    result = extractor.extract(source=str(tmp_path))

    sw_tests = _entity_names(result, "SW_Test")
    assert "aes_smoketest" in sw_tests

    ent = next(e for e in result.entities if e.name == "aes_smoketest")
    assert ent.layer == SW_TEST_SOURCE
    assert SW_TEST_SOURCE in ent.extractor_source


# ---------------------------------------------------------------------------
# test_accesses_csr_when_known
# ---------------------------------------------------------------------------


def test_accesses_csr_when_known(tmp_path):
    src = """\
#include "mmio.h"
void test_main(void) {
  mmio_region_write32(base, AES_CTRL_SHADOWED_REG_OFFSET, 0x01);
  uint32_t v = mmio_region_read32(base, AES_STATUS_REG_OFFSET);
}
"""
    _write(tmp_path / "aes_smoke_test.c", src)
    extractor = SWTestExtractor(
        known_entity_names=[
            "aes",
            "AES.CTRL_SHADOWED",
            "aes.ctrl_shadowed",
            "aes.status",
        ]
    )
    result = extractor.extract(source=str(tmp_path))

    csr_triples = _triples(result, predicate="accesses_csr")
    csr_objects = {t.object for t in csr_triples}
    assert any("ctrl_shadowed" in obj.lower() for obj in csr_objects), (
        f"Expected ctrl_shadowed in {csr_objects}"
    )
    assert any("status" in obj.lower() for obj in csr_objects), (
        f"Expected status in {csr_objects}"
    )


# ---------------------------------------------------------------------------
# test_module_name_in_filename_links
# ---------------------------------------------------------------------------


def test_module_name_in_filename_links(tmp_path):
    # Reframed: filename substring no longer matches; use a #include signal.
    _write(
        tmp_path / "aes_smoke_test.c",
        '#include "dif_aes.h"\nvoid test_main(void) {}\n',
    )
    extractor = SWTestExtractor(known_entity_names=["aes", "clkmgr"])
    result = extractor.extract(source=str(tmp_path))

    tm = _triples(result, predicate="tests_module")
    resolved = [t for t in tm if t.resolved]
    assert len(resolved) == 1
    assert resolved[0].subject == "aes_smoke_test"
    assert resolved[0].object == "aes"
    assert resolved[0].confidence_tier == "high"


# ---------------------------------------------------------------------------
# test_module_name_not_in_filename_no_link
# ---------------------------------------------------------------------------


def test_module_name_not_in_filename_no_link(tmp_path):
    # File contains test_main → is_test=True, no DIF call resolves, no
    # filename match → low-tier unresolved sentinel edge to "<unknown>".
    _write(tmp_path / "uart_smoke_test.c", "void test_main(void) {}\n")
    extractor = SWTestExtractor(known_entity_names=["aes", "clkmgr"])
    result = extractor.extract(source=str(tmp_path))

    tm = _triples(result, predicate="tests_module")
    # No resolved tests_module edges.
    resolved = [t for t in tm if t.resolved]
    assert len(resolved) == 0
    # One unresolved low-tier sentinel edge.
    assert len(tm) == 1
    assert tm[0].object == "<unknown>"
    assert tm[0].confidence_tier == "low"
    assert tm[0].resolved is False


# ---------------------------------------------------------------------------
# test_round_trip
# ---------------------------------------------------------------------------


def test_round_trip(tmp_path):
    src = """\
#include "mmio.h"
void test_main(void) {
  abs_mmio_write32(base + AES_STATUS_REG_OFFSET, 0);
}
"""
    _write(tmp_path / "aes_entropy_test.c", src)
    extractor = SWTestExtractor(known_entity_names=["aes"])
    result = extractor.extract(source=str(tmp_path))

    backend = NetworkXBackend()
    backend.upsert_entities(result.entities)
    backend.upsert_triples(result.triples)

    node_names = set(backend.get_all_node_names_and_aliases().keys())
    assert "aes_entropy_test" in node_names

    outgoing = backend.get_outgoing_edges("aes_entropy_test")
    predicates = {e.predicate for e in outgoing}
    assert "tests_module" in predicates


# ---------------------------------------------------------------------------
# test_layer_tags
# ---------------------------------------------------------------------------


def test_layer_tags(tmp_path):
    _write(tmp_path / "aes_test.c", "void test_main(void) {}\n")
    extractor = SWTestExtractor(known_entity_names=["aes"])
    result = extractor.extract(source=str(tmp_path))

    for e in result.entities:
        assert e.layer == SW_TEST_SOURCE
    for t in result.triples:
        assert t.layer == SW_TEST_SOURCE


# ---------------------------------------------------------------------------
# test_dif_layer_csr_access
# ---------------------------------------------------------------------------


def test_dif_layer_csr_access(tmp_path):
    src = """\
#include "dif_aes.h"
void test_main(void) {
    dif_aes_t aes;
    dif_aes_init_from_dt(kDtAes, &aes);
    dif_aes_reset(&aes);
}
"""
    _write(tmp_path / "aes_smoketest.c", src)
    extractor = SWTestExtractor(known_entity_names=["aes"])
    result = extractor.extract(source=str(tmp_path))

    csr_triples = _triples(result, predicate="accesses_csr")
    assert len(csr_triples) >= 1
    objects = {t.object for t in csr_triples}
    assert any("aes" in obj.lower() for obj in objects)


# ---------------------------------------------------------------------------
# Phase 2: ProjectConventions wiring — generic CSR API + extensions
# ---------------------------------------------------------------------------


def test_swtest_custom_csr_access_api_pattern_generic_call(tmp_path):
    """Custom CSR-access API list lets a non-OT codebase using
    ``frobnicator_csr_write32(...)`` produce ``accesses_csr`` edges."""
    from kgweave.knowledge_graph.extraction.sw_test_extractor import (
        SWTestExtractor,
    )

    src = (
        "int main(void){\n"
        "  frobnicator_csr_write32(handle, FROBNICATOR_CTRL_REG_OFFSET, 0);\n"
        "  return 0;\n"
        "}\n"
    )
    (tmp_path / "frob_smoke.c").write_text(src)
    ex = SWTestExtractor(
        known_entity_names=["frobnicator"],
        csr_access_api_patterns=["frobnicator_csr_write32"],
    )
    res = ex.extract(source=str(tmp_path))
    csr_edges = [t for t in res.triples if t.predicate == "accesses_csr"]
    assert csr_edges, "expected ≥1 accesses_csr edge from custom API call"


def test_swtest_csr_offset_suffixes_configurable(tmp_path):
    """A project using ``_REG_ADDR`` instead of ``_REG_OFFSET`` can supply a
    custom ``csr_offset_suffixes`` list and have its bare-offset references
    map to CSR access edges."""
    from kgweave.knowledge_graph.extraction.sw_test_extractor import (
        SWTestExtractor,
    )

    src = (
        "int main(void){\n"
        "  *(volatile uint32_t*)WIDGET_CTRL_REG_ADDR = 1;\n"
        "  return 0;\n"
        "}\n"
    )
    (tmp_path / "widget_test.c").write_text(src)
    ex = SWTestExtractor(
        known_entity_names=["widget"],
        csr_offset_suffixes=["_REG_ADDR"],
    )
    res = ex.extract(source=str(tmp_path))
    csr_edges = [t for t in res.triples if t.predicate == "accesses_csr"]
    assert csr_edges, "expected accesses_csr edges with custom suffix"


def test_swtest_extensions_pickup_cc(tmp_path):
    """When sw_test_extensions includes ``.cc``, C++ test files are walked
    in addition to ``.c`` files."""
    from kgweave.knowledge_graph.extraction.sw_test_extractor import (
        SWTestExtractor,
    )

    (tmp_path / "gizmo_test.cc").write_text(
        '#include "gizmo.h"\nint main(void){ return 0; }\n'
    )
    ex = SWTestExtractor(
        known_entity_names=["gizmo"],
        sw_test_extensions=[".c", ".cc"],
    )
    res = ex.extract(source=str(tmp_path))
    sw_test_names = {e.name for e in res.entities if e.type == "SW_Test"}
    assert "gizmo_test" in sw_test_names


# ---------------------------------------------------------------------------
# test_sw_test_extractor_no_import_re  (TDD – fails before regex removal)
# ---------------------------------------------------------------------------


def test_sw_test_extractor_no_import_re():
    """sw_test_extractor must not import the ``re`` module at module level.

    The ``_MODULE_NAME_RE``, ``_MMIO_OFFSET_RE``, ``_BARE_OFFSET_RE``,
    ``_build_mmio_regex``, and ``_build_bare_offset_regex`` should all use
    structural token scanning instead of regex compilation.
    """
    import ast
    import importlib.util
    import pathlib

    src_path = pathlib.Path(
        importlib.util.find_spec(
            "kgweave.knowledge_graph.extraction.sw_test_extractor"
        ).origin
    )
    tree = ast.parse(src_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "re", (
                        "sw_test_extractor still does 'import re' — "
                        "replace regex with structural token scanning"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "re", (
                    "sw_test_extractor still does 'from re import ...' — "
                    "replace regex with structural token scanning"
                )


def test_sw_test_extractor_mmio_tab_whitespace(tmp_path):
    """MMIO offset scan must work when the call uses tab indentation and
    multi-line argument lists — a case where a strict line-oriented regex
    would miss the offset constant but structural token scanning finds it."""
    src = (
        "void test_main(void) {\n"
        "\tmmio_region_write32(\n"
        "\t\tbase,\n"
        "\t\tAES_CTRL_SHADOWED_REG_OFFSET,\n"
        "\t\t0x01\n"
        "\t);\n"
        "}\n"
    )
    (tmp_path / "aes_tab_test.c").write_text(src)
    ex = SWTestExtractor(
        known_entity_names=["aes", "aes.ctrl_shadowed"],
    )
    res = ex.extract(source=str(tmp_path))
    csr_edges = [t for t in res.triples if t.predicate == "accesses_csr"]
    assert csr_edges, (
        "accesses_csr edge expected for multi-line MMIO call with tab indentation"
    )
