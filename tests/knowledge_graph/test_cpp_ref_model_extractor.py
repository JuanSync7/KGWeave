# @summary
# Tests for CppRefModelExtractor and extract_dpi_boundaries.
# Covers: CFile entity emission, CFunction extraction, comment skipping,
# local-include-only filtering, implements_dpi fusion, round-trip to backend,
# and a smoke test against the real OpenTitan AES model directory.
# @end-summary
"""Tests for CppRefModelExtractor and extract_dpi_boundaries."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.extraction.cpp_extractor import (
    CppRefModelExtractor,
    CPP_REF_MODEL_SOURCE,
    extract_dpi_boundaries,
    build_dpi_boundary_entities,
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


def _triple_predicates(result, subject=None, predicate=None):
    triples = result.triples
    if subject:
        triples = [t for t in triples if t.subject == subject]
    if predicate:
        triples = [t for t in triples if t.predicate == predicate]
    return triples


# ---------------------------------------------------------------------------
# test_cfile_entity_emitted
# ---------------------------------------------------------------------------


def test_cfile_entity_emitted(tmp_path):
    _write(tmp_path / "foo.cc", "int bar(int x) { return x; }\n")
    extractor = CppRefModelExtractor()
    result = extractor.extract(source=str(tmp_path))

    cfiles = _entity_names(result, "CFile")
    assert "foo.cc" in cfiles
    cfile_ent = next(e for e in result.entities if e.name == "foo.cc")
    assert cfile_ent.type == "CFile"
    assert cfile_ent.layer == CPP_REF_MODEL_SOURCE
    assert CPP_REF_MODEL_SOURCE in cfile_ent.extractor_source


# ---------------------------------------------------------------------------
# test_cfunction_extracted_simple
# ---------------------------------------------------------------------------


def test_cfunction_extracted_simple(tmp_path):
    _write(tmp_path / "model.c", "int foo(int x) {\n  return x;\n}\n")
    extractor = CppRefModelExtractor()
    result = extractor.extract(source=str(tmp_path))

    cfuncs = _entity_names(result, "CFunction")
    assert "foo" in cfuncs

    defined = _triple_predicates(result, predicate="defined_in")
    subjects = {t.subject for t in defined}
    assert "foo" in subjects
    objects = {t.object for t in defined if t.subject == "foo"}
    assert "model.c" in objects


# ---------------------------------------------------------------------------
# test_cfunction_skipped_in_comment
# ---------------------------------------------------------------------------


def test_cfunction_skipped_in_comment(tmp_path):
    src = """\
/* This is a block comment.
   int commented_func(int x) {
   This should NOT be extracted.
   }
*/
int real_func(int x) { return x; }
"""
    _write(tmp_path / "block.c", src)
    extractor = CppRefModelExtractor()
    result = extractor.extract(source=str(tmp_path))

    cfuncs = _entity_names(result, "CFunction")
    assert "commented_func" not in cfuncs
    assert "real_func" in cfuncs


# ---------------------------------------------------------------------------
# test_includes_local_only
# ---------------------------------------------------------------------------


def test_includes_local_only(tmp_path):
    src = """\
#include "local.h"
#include <stdio.h>
#include "another.h"
#include <stdlib.h>

void func_a(void) {}
"""
    _write(tmp_path / "main.c", src)
    extractor = CppRefModelExtractor()
    result = extractor.extract(source=str(tmp_path))

    includes = _triple_predicates(result, predicate="includes")
    objects = {t.object for t in includes}
    assert "local.h" in objects
    assert "another.h" in objects
    assert "stdio.h" not in objects
    assert "stdlib.h" not in objects


# ---------------------------------------------------------------------------
# test_implements_dpi_when_known
# ---------------------------------------------------------------------------


def test_implements_dpi_when_known(tmp_path):
    _write(tmp_path / "dpi.c", "void aes_dpi_encrypt(int x) { }\n")
    extractor = CppRefModelExtractor(known_entity_names=["aes_dpi_encrypt"])
    result = extractor.extract(source=str(tmp_path))

    dpi_triples = _triple_predicates(result, predicate="implements_dpi")
    assert len(dpi_triples) == 1
    assert dpi_triples[0].subject == "aes_dpi_encrypt"
    assert dpi_triples[0].layer == CPP_REF_MODEL_SOURCE


# ---------------------------------------------------------------------------
# test_no_match_no_dpi_edge
# ---------------------------------------------------------------------------


def test_no_match_no_dpi_edge(tmp_path):
    _write(tmp_path / "dpi.c", "void some_other_func(int x) { }\n")
    extractor = CppRefModelExtractor(known_entity_names=["aes_dpi_encrypt"])
    result = extractor.extract(source=str(tmp_path))

    dpi_triples = _triple_predicates(result, predicate="implements_dpi")
    assert len(dpi_triples) == 0


# ---------------------------------------------------------------------------
# test_round_trip_extract_to_backend
# ---------------------------------------------------------------------------


def test_round_trip_extract_to_backend(tmp_path):
    _write(tmp_path / "aes.c", "int aes_encrypt(int x) { return x; }\n")
    extractor = CppRefModelExtractor()
    result = extractor.extract(source=str(tmp_path))

    backend = NetworkXBackend()
    backend.upsert_entities(result.entities)
    backend.upsert_triples(result.triples)

    node_names = set(backend.get_all_node_names_and_aliases().keys())
    assert "aes.c" in node_names
    assert "aes_encrypt" in node_names

    outgoing = backend.get_outgoing_edges("aes_encrypt")
    predicates = {e.predicate for e in outgoing}
    assert "defined_in" in predicates


# ---------------------------------------------------------------------------
# test_multiple_extensions_covered
# ---------------------------------------------------------------------------


def test_multiple_extensions_covered(tmp_path):
    _write(tmp_path / "a.c", "void fa(void) {}\n")
    _write(tmp_path / "b.cc", "void fb(void) {}\n")
    _write(tmp_path / "c.cpp", "void fc(void) {}\n")
    _write(tmp_path / "d.h", "void fd(void) {}\n")
    _write(tmp_path / "e.hh", "void fe(void) {}\n")
    _write(tmp_path / "f.hpp", "void ff(void) {}\n")
    _write(tmp_path / "skip.txt", "void fskip(void) {}\n")

    extractor = CppRefModelExtractor()
    result = extractor.extract(source=str(tmp_path))

    cfiles = _entity_names(result, "CFile")
    assert {"a.c", "b.cc", "c.cpp", "d.h", "e.hh", "f.hpp"} == cfiles
    assert "skip.txt" not in cfiles


# ---------------------------------------------------------------------------
# test_layer_tags_on_all_artifacts
# ---------------------------------------------------------------------------


def test_layer_tags_on_all_artifacts(tmp_path):
    _write(tmp_path / "x.c", 'int g(int a) { return a; }\n#include "y.h"\n')
    extractor = CppRefModelExtractor()
    result = extractor.extract(source=str(tmp_path))

    for e in result.entities:
        assert e.layer == CPP_REF_MODEL_SOURCE, f"entity {e.name} missing layer"
    for t in result.triples:
        assert t.layer == CPP_REF_MODEL_SOURCE, f"triple {t} missing layer"


# ---------------------------------------------------------------------------
# test_extract_dpi_boundaries
# ---------------------------------------------------------------------------


def test_extract_dpi_boundaries(tmp_path):
    sv = tmp_path / "pkg.sv"
    sv.write_text(
        'package p;\n'
        '  import "DPI-C" context function void c_dpi_aes_crypt_block(\n'
        '    input int x);\n'
        '  import "DPI-C" function void c_dpi_aes_key_expand(\n'
        '    input int y);\n'
        'endpackage\n'
    )
    names = extract_dpi_boundaries([str(sv)])
    assert "c_dpi_aes_crypt_block" in names
    assert "c_dpi_aes_key_expand" in names


# ---------------------------------------------------------------------------
# test_real_aes_model_smoke
# ---------------------------------------------------------------------------

_AES_MODEL = (
    Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "aes" / "model"
)


@pytest.mark.skipif(
    not _AES_MODEL.exists(),
    reason="OpenTitan AES model directory not present",
)
def test_real_aes_model_smoke():
    extractor = CppRefModelExtractor()
    result = extractor.extract(source=str(_AES_MODEL))

    cfuncs = [e for e in result.entities if e.type == "CFunction"]
    cfiles = [e for e in result.entities if e.type == "CFile"]
    assert len(cfuncs) >= 1, "Expected at least one CFunction from AES model"
    assert len(cfiles) >= 1, "Expected at least one CFile from AES model"

    defined_in_triples = [t for t in result.triples if t.predicate == "defined_in"]
    assert len(defined_in_triples) >= 1
