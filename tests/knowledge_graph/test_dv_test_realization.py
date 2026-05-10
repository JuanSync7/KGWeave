# @summary
# Tests for DVTestRealizationExtractor — directory-based test file realization,
# suffix stripping heuristics, case-insensitive DVTest matching, recursive walk,
# orphan SV_File emission for unmatched files, and round-trip backend integration.
# @end-summary
"""TDD coverage for the DV test file realization extractor."""

from __future__ import annotations

import pytest
from pathlib import Path

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.extraction.dv_test_realization_extractor import (
    DVTestRealizationExtractor,
    DV_TEST_REALIZATION_SOURCE,
)


def _make() -> DVTestRealizationExtractor:
    return DVTestRealizationExtractor()


def test_strips_vseq_suffix() -> None:
    """File foo_vseq.sv with known DVTest 'foo' emits realized_by edge."""
    tmp_dir = Path("/tmp/kg_test_vseq")
    tmp_dir.mkdir(exist_ok=True)
    try:
        test_file = tmp_dir / "foo_vseq.sv"
        test_file.write_text("// test file\n")

        extractor = DVTestRealizationExtractor(known_entity_names=["foo"])
        result = extractor.extract(text="", source=str(tmp_dir))

        sv_files = [e for e in result.entities if e.type == "SV_File"]
        assert len(sv_files) == 1
        assert sv_files[0].name == "foo_vseq.sv"

        realized_by = [t for t in result.triples if t.predicate == "realized_by"]
        assert len(realized_by) == 1
        assert realized_by[0].subject == "foo"
        assert realized_by[0].object == "foo_vseq.sv"
    finally:
        test_file.unlink(missing_ok=True)
        tmp_dir.rmdir()


def test_strips_test_suffix() -> None:
    """File bar_test.sv with known DVTest 'bar' emits realized_by edge."""
    tmp_dir = Path("/tmp/kg_test_test_suffix")
    tmp_dir.mkdir(exist_ok=True)
    try:
        test_file = tmp_dir / "bar_test.sv"
        test_file.write_text("// test file\n")

        extractor = DVTestRealizationExtractor(known_entity_names=["bar"])
        result = extractor.extract(text="", source=str(tmp_dir))

        sv_files = [e for e in result.entities if e.type == "SV_File"]
        assert len(sv_files) == 1
        assert sv_files[0].name == "bar_test.sv"

        realized_by = [t for t in result.triples if t.predicate == "realized_by"]
        assert len(realized_by) == 1
        assert realized_by[0].subject == "bar"
        assert realized_by[0].object == "bar_test.sv"
    finally:
        test_file.unlink(missing_ok=True)
        tmp_dir.rmdir()


def test_no_match_emits_sv_file_only() -> None:
    """File with no DVTest match still emits SV_File entity, no realized_by edge."""
    tmp_dir = Path("/tmp/kg_test_orphan")
    tmp_dir.mkdir(exist_ok=True)
    try:
        test_file = tmp_dir / "unknown_test.sv"
        test_file.write_text("// orphan test file\n")

        extractor = DVTestRealizationExtractor(known_entity_names=["foo", "bar"])
        result = extractor.extract(text="", source=str(tmp_dir))

        sv_files = [e for e in result.entities if e.type == "SV_File"]
        assert len(sv_files) == 1
        assert sv_files[0].name == "unknown_test.sv"

        realized_by = [t for t in result.triples if t.predicate == "realized_by"]
        assert len(realized_by) == 0
    finally:
        test_file.unlink(missing_ok=True)
        tmp_dir.rmdir()


def test_case_insensitive_match() -> None:
    """File foo_vseq.sv matches known DVTest 'FOO' (case-insensitive)."""
    tmp_dir = Path("/tmp/kg_test_case_insensitive")
    tmp_dir.mkdir(exist_ok=True)
    try:
        test_file = tmp_dir / "foo_vseq.sv"
        test_file.write_text("// test file\n")

        extractor = DVTestRealizationExtractor(known_entity_names=["FOO"])
        result = extractor.extract(text="", source=str(tmp_dir))

        realized_by = [t for t in result.triples if t.predicate == "realized_by"]
        assert len(realized_by) == 1
        assert realized_by[0].subject == "FOO"
    finally:
        test_file.unlink(missing_ok=True)
        tmp_dir.rmdir()


def test_recursive_walk_depth_2() -> None:
    """Walk finds .sv files up to depth 2 (includes subdirs like dv/tests/smoke)."""
    tmp_dir = Path("/tmp/kg_test_recursive")
    tmp_dir.mkdir(exist_ok=True)
    subdir = tmp_dir / "smoke"
    subdir.mkdir(exist_ok=True)
    try:
        file1 = tmp_dir / "aes_smoke_vseq.sv"
        file2 = subdir / "aes_stress_vseq.sv"
        file1.write_text("// smoke\n")
        file2.write_text("// stress\n")

        extractor = DVTestRealizationExtractor(
            known_entity_names=["aes_smoke", "aes_stress"]
        )
        result = extractor.extract(text="", source=str(tmp_dir))

        sv_files = [e for e in result.entities if e.type == "SV_File"]
        sv_names = {e.name for e in sv_files}
        assert "aes_smoke_vseq.sv" in sv_names
        assert "aes_stress_vseq.sv" in sv_names
    finally:
        file1.unlink(missing_ok=True)
        file2.unlink(missing_ok=True)
        subdir.rmdir()
        tmp_dir.rmdir()


def test_suffix_priority_vseq_over_test() -> None:
    """When file ends in _vseq.sv, use that, not _test.sv (priority order)."""
    tmp_dir = Path("/tmp/kg_test_suffix_priority")
    tmp_dir.mkdir(exist_ok=True)
    try:
        test_file = tmp_dir / "foo_vseq_test.sv"
        test_file.write_text("// file\n")

        extractor = DVTestRealizationExtractor(known_entity_names=["foo_vseq"])
        result = extractor.extract(text="", source=str(tmp_dir))

        realized_by = [t for t in result.triples if t.predicate == "realized_by"]
        assert len(realized_by) == 1
        assert realized_by[0].subject == "foo_vseq"
    finally:
        test_file.unlink(missing_ok=True)
        tmp_dir.rmdir()


def test_round_trip_extract_to_backend() -> None:
    """Extract SV_File entities, ingest into backend, verify fusion + layer tags."""
    tmp_dir = Path("/tmp/kg_test_backend")
    tmp_dir.mkdir(exist_ok=True)
    try:
        test_file = tmp_dir / "aes_smoke_vseq.sv"
        test_file.write_text("// test\n")

        extractor = DVTestRealizationExtractor(known_entity_names=["aes_smoke"])
        result = extractor.extract(text="", source=str(tmp_dir))

        backend = NetworkXBackend()
        backend.upsert_entities(result.entities)
        backend.upsert_triples(result.triples)

        all_entities = backend.get_all_entities()
        sv_files = [e for e in all_entities if e.type == "SV_File"]
        assert len(sv_files) == 1
        assert sv_files[0].name == "aes_smoke_vseq.sv"
        assert sv_files[0].layer == DV_TEST_REALIZATION_SOURCE

        realized_by_edges = [t for t in result.triples if t.predicate == "realized_by"]
        assert len(realized_by_edges) == 1
        assert realized_by_edges[0].layer == DV_TEST_REALIZATION_SOURCE
    finally:
        test_file.unlink(missing_ok=True)
        tmp_dir.rmdir()


@pytest.mark.skipif(
    not Path.home().joinpath("RagWeave/opentitan_data/hw/ip/aes/dv/tests").exists(),
    reason="OpenTitan AES DV tests not found; set KGWEAVE_OPENTITAN_ROOT or clone opentitan"
)
def test_real_aes_dv_tests_smoke() -> None:
    """Smoke test against real OpenTitan AES dv/tests (if available)."""
    dv_tests = Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "aes" / "dv" / "tests"
    assert dv_tests.exists()

    test_names = [
        "aes_smoke",
        "aes_stress",
        "aes_enc_dec_single",
        "aes_pipelined",
    ]
    extractor = DVTestRealizationExtractor(known_entity_names=test_names)
    result = extractor.extract(text="", source=str(dv_tests))

    sv_files = [e for e in result.entities if e.type == "SV_File"]
    assert len(sv_files) > 0, "Should find .sv files in dv/tests"

    realized_by_edges = [t for t in result.triples if t.predicate == "realized_by"]
    assert len(realized_by_edges) >= 1, "Should find at least 1 realized_by edge"

    for edge in realized_by_edges:
        assert edge.subject in test_names
        assert edge.object.endswith(".sv")


def test_empty_directory_returns_empty_result() -> None:
    """Walking an empty directory returns empty result."""
    tmp_dir = Path("/tmp/kg_test_empty")
    tmp_dir.mkdir(exist_ok=True)
    try:
        extractor = DVTestRealizationExtractor(known_entity_names=["foo"])
        result = extractor.extract(text="", source=str(tmp_dir))
        assert len(result.entities) == 0
        assert len(result.triples) == 0
    finally:
        tmp_dir.rmdir()


def test_nonexistent_directory_returns_empty_result() -> None:
    """Walking a nonexistent directory returns empty result (no error)."""
    nonexistent = Path("/tmp/kg_test_nonexistent_xyz_999")
    extractor = DVTestRealizationExtractor(known_entity_names=["foo"])
    result = extractor.extract(text="", source=str(nonexistent))
    assert len(result.entities) == 0
    assert len(result.triples) == 0


def test_empty_source_returns_empty_result() -> None:
    """Calling extract with empty source returns empty result."""
    extractor = DVTestRealizationExtractor(known_entity_names=["foo"])
    result = extractor.extract(text="", source="")
    assert len(result.entities) == 0
    assert len(result.triples) == 0


def test_extractor_name_property() -> None:
    """Extractor name property returns correct value."""
    extractor = DVTestRealizationExtractor()
    assert extractor.name == DV_TEST_REALIZATION_SOURCE


# ---------------------------------------------------------------------------
# Phase 3 D9: custom DV test file strip suffixes
# ---------------------------------------------------------------------------


def test_dv_test_realization_custom_strip_suffixes(tmp_path):
    """A non-OT DV codebase uses ``<name>_scenario.sv`` for test files;
    the extractor must fuse via a custom strip-suffix list."""
    from kgweave.knowledge_graph.extraction.dv_test_realization_extractor import (
        DVTestRealizationExtractor,
    )
    from kgweave.knowledge_graph.common.types import ProjectConventions

    test_file = tmp_path / "wibble_smoke_scenario.sv"
    test_file.write_text("// scenario file\n")

    pc = ProjectConventions(dv_test_file_strip_suffixes=["_scenario.sv", ".sv"])
    extractor = DVTestRealizationExtractor(
        known_entity_names=["wibble_smoke"],
        project_conventions=pc,
    )
    result = extractor.extract(text="", source=str(tmp_path))
    realized = [t for t in result.triples if t.predicate == "realized_by"]
    assert any(t.subject == "wibble_smoke" for t in realized)
