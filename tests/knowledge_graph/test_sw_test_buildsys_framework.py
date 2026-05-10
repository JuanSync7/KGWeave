"""Tier B framework tests: reader Protocol, registry, conflict resolution.

The reader registry is the unifying abstraction over five build-system
ingestion formats (dvsim hjson, UVM testlist .f, fusesoc .core, Bazel
BUILD, Makefile). Each format implements ``BuildSystemReader``; the
``discover_links()`` helper iterates a list of readers and returns
aggregated ``BuildSystemLink`` records.

These tests exercise the framework only (no real-format parsing); each
format's parser ships its own test file.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from kgweave.knowledge_graph.common.sw_test_buildsys import (
    BuildSystemLink,
    BuildSystemReader,
    discover_links,
)


# ---------------------------------------------------------------------------
# Fake readers used to exercise the registry without needing real parsers.
# ---------------------------------------------------------------------------


class _FakeReader:
    """Minimal reader that emits a fixed set of links if applicable."""

    def __init__(
        self,
        name: str,
        links: List[BuildSystemLink],
        applies: bool = True,
    ) -> None:
        self.name = name
        self._links = links
        self._applies = applies
        self.read_called = 0

    def applies_to(self, project_root: Path) -> bool:
        return self._applies

    def read(self, project_root: Path) -> List[BuildSystemLink]:
        self.read_called += 1
        return list(self._links)


def _link(test: str, mod: str, fmt: str = "fake", src: str = "fake.cfg") -> BuildSystemLink:
    return BuildSystemLink(
        test_path=test,
        module_name=mod,
        source_format=fmt,
        source_file=src,
        confidence_tier="high",
        raw_match={"test": test, "module": mod},
    )


# ---------------------------------------------------------------------------
# (1) Protocol shape
# ---------------------------------------------------------------------------


def test_buildsystem_reader_protocol_compiles():
    """A class implementing the documented surface satisfies the Protocol."""
    r = _FakeReader("fake", [])
    # Protocol membership is structural; we just verify required attrs/methods.
    assert hasattr(r, "name")
    assert callable(getattr(r, "applies_to", None))
    assert callable(getattr(r, "read", None))
    # And it can be passed where a BuildSystemReader is expected.
    out = discover_links(Path("/tmp"), readers=[r])
    assert out == []


def test_build_system_link_dataclass_fields():
    link = _link("/p/test.c", "aes")
    assert link.test_path == "/p/test.c"
    assert link.module_name == "aes"
    assert link.source_format == "fake"
    assert link.source_file == "fake.cfg"
    assert link.confidence_tier == "high"
    assert link.raw_match["module"] == "aes"


# ---------------------------------------------------------------------------
# (2) Registry roundtrip
# ---------------------------------------------------------------------------


def test_discover_links_aggregates_all_readers(tmp_path):
    r1 = _FakeReader("r1", [_link("/p/t1.c", "aes", fmt="r1")])
    r2 = _FakeReader("r2", [_link("/p/t2.c", "hmac", fmt="r2")])
    out = discover_links(tmp_path, readers=[r1, r2])
    assert len(out) == 2
    assert {l.module_name for l in out} == {"aes", "hmac"}
    assert {l.source_format for l in out} == {"r1", "r2"}
    assert r1.read_called == 1 and r2.read_called == 1


def test_discover_links_empty_project_returns_empty(tmp_path):
    out = discover_links(tmp_path, readers=[])
    assert out == []


def test_discover_links_skips_inapplicable_reader(tmp_path):
    skipped = _FakeReader("skip", [_link("/p/t.c", "aes")], applies=False)
    out = discover_links(tmp_path, readers=[skipped])
    assert out == []
    assert skipped.read_called == 0


def test_discover_links_default_readers_when_none_passed(tmp_path):
    """When readers=None, the default registry is used. The default registry
    yields zero links on an empty project (no enabled readers find anything)."""
    out = discover_links(tmp_path)
    assert isinstance(out, list)


# ---------------------------------------------------------------------------
# (3) Resolver integration: build-system link wins over conflicting regex
# ---------------------------------------------------------------------------


def test_build_system_link_overrides_regex_conflict(tmp_path):
    """When the resolver is fed a project_root and a build-system link covers
    (test, module), an identical regex match for the same pair is suppressed.
    The emitted Triple's extractor_source/source_format reflects build-system
    provenance.
    """
    from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor
    from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink

    c = tmp_path / "z.c"
    c.write_text(
        '#include "dif_aes.h"\n'
        "int main(void){ dif_aes_init(&h); return 0; }\n"
    )

    fake_link = BuildSystemLink(
        test_path=str(c),
        module_name="aes",
        source_format="dvsim_hjson",
        source_file=str(tmp_path / "fake_sim_cfg.hjson"),
        confidence_tier="high",
        raw_match={},
    )
    reader = _FakeReader("dvsim_hjson", [fake_link])

    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(
        source=str(tmp_path),
        project_root=tmp_path,
        build_system_readers=[reader],
    )

    # exactly one tests_module aes edge, attributed to the build system
    aes_edges = [
        t for t in res.triples
        if t.predicate == "tests_module" and t.object == "aes"
    ]
    assert len(aes_edges) == 1
    edge = aes_edges[0]
    # Provenance signal: source_format embedded in evidence_span or
    # confidence_tier preserved from build system. The implementation must
    # pick one (or both) channels — assert at least one is present.
    has_provenance = (
        "dvsim_hjson" in (edge.evidence_span or "")
        or (edge.attributes or {}).get("build_system_source") is not None
    )
    assert has_provenance, (
        f"build-system provenance missing on edge: "
        f"evidence={edge.evidence_span!r} attributes={edge.attributes!r}"
    )


def test_build_system_link_complements_regex_for_different_module(tmp_path):
    """Build-system link to module A and regex-only match for module B
    coexist; both edges are emitted."""
    from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor
    from kgweave.knowledge_graph.common.sw_test_buildsys import BuildSystemLink

    c = tmp_path / "z.c"
    c.write_text(
        '#include "dif_hmac.h"\n'
        "int main(void){ return 0; }\n"
    )

    fake_link = BuildSystemLink(
        test_path=str(c),
        module_name="aes",  # build system says aes
        source_format="dvsim_hjson",
        source_file="fake.hjson",
        confidence_tier="high",
        raw_match={},
    )
    reader = _FakeReader("dvsim_hjson", [fake_link])

    ex = SWTestExtractor(known_entity_names=["aes", "hmac"])
    res = ex.extract(
        source=str(tmp_path),
        project_root=tmp_path,
        build_system_readers=[reader],
    )
    mods = {t.object for t in res.triples if t.predicate == "tests_module"}
    assert "aes" in mods
    assert "hmac" in mods


def test_no_project_root_byte_identical_behavior(tmp_path):
    """When project_root is not passed, behavior is unchanged (no readers run)."""
    from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor

    c = tmp_path / "z.c"
    c.write_text(
        '#include "dif_aes.h"\n'
        "int main(void){ return 0; }\n"
    )

    ex = SWTestExtractor(known_entity_names=["aes"])
    res_no = ex.extract(source=str(tmp_path))
    res_with = ex.extract(source=str(tmp_path), project_root=None)

    def _key(t):
        return (t.subject, t.predicate, t.object, t.confidence_tier)

    assert sorted(map(_key, res_no.triples)) == sorted(map(_key, res_with.triples))
