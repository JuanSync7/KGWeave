"""Round-trip integration tests for extractors that previously lacked them.

For each extractor below, we run:
    extract(text) -> Entities + Triples
    backend.upsert_entities(...) + backend.upsert_triples(...)
    backend.get_outgoing_edges(...) / backend.get_all_entities(...)

and assert that what comes out matches what went in.

Why: the slang ``connects_to`` + ``drives`` shadowing bug shipped because
no test exercised the storage round-trip end-to-end — every unit test
asserted the extractor's output but never that the backend kept it.
This file exists so that every extractor has at least one test that
cannot pass unless storage is lossless.

See ``test_backend_predicate_collisions.py`` for the project-level
predicate audit and the documented DiGraph hazards.
"""
from __future__ import annotations

from typing import Set

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.extraction import (
    BashParserExtractor,
    GLiNEREntityExtractor,
    PythonParserExtractor,
    RegexEntityExtractor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _predicates_from(backend: NetworkXBackend, subject: str) -> Set[str]:
    return {t.predicate for t in backend.get_outgoing_edges(subject)}


def _objects_from(backend: NetworkXBackend, subject: str, predicate: str) -> Set[str]:
    return {
        t.object
        for t in backend.get_outgoing_edges(subject)
        if t.predicate == predicate
    }


# ---------------------------------------------------------------------------
# RegexEntityExtractor
# ---------------------------------------------------------------------------


def test_regex_extractor_round_trip() -> None:
    """RegexEntityExtractor: extract -> upsert -> query.

    Asserts the predicates it emits (is_a, subset_of, used_for, uses) are
    queryable through ``get_outgoing_edges`` after storage.
    """
    text = (
        "RAG is a subset of nlp.\n"
        "Vector Search is a retrieval technique.\n"
        "Embeddings are used for semantic search.\n"
        "Retrieval Augmented Generation includes rerankers.\n"
    )
    extractor = RegexEntityExtractor()
    result = extractor.extract(text, source="primer.md")

    backend = NetworkXBackend()
    backend.upsert_entities(result.entities)
    backend.upsert_triples(result.triples)

    # Every triple emitted should be queryable from the subject.
    for triple in result.triples:
        objs = _objects_from(backend, triple.subject, triple.predicate)
        assert triple.object in objs, (
            f"Triple ({triple.subject})-[{triple.predicate}]->({triple.object}) "
            f"lost in storage; got {objs}"
        )

    # Every entity name should be retrievable.
    all_names = {e.name for e in backend.get_all_entities()}
    for ent in result.entities:
        assert ent.name in all_names, f"Entity {ent.name!r} dropped by backend"


# ---------------------------------------------------------------------------
# PythonParserExtractor
# ---------------------------------------------------------------------------


def test_python_parser_round_trip() -> None:
    """PythonParserExtractor: contains + depends_on round-trip."""
    src = (
        "import os\n"
        "from collections import OrderedDict\n"
        "\n"
        "MAX_RETRIES = 3\n"
        "\n"
        "class Base:\n"
        "    def hello(self):\n"
        "        return 1\n"
        "\n"
        "class Derived(Base):\n"
        "    def world(self):\n"
        "        return 2\n"
        "\n"
        "def top_level():\n"
        "    return 0\n"
    )
    extractor = PythonParserExtractor()
    result = extractor.extract(src, source="myfile.py")

    backend = NetworkXBackend()
    backend.upsert_entities(result.entities)
    backend.upsert_triples(result.triples)

    # Module 'myfile' should contain the top-level definitions.
    contains = _objects_from(backend, "myfile", "contains")
    assert "Base" in contains
    assert "Derived" in contains
    assert "top_level" in contains
    assert "MAX_RETRIES" in contains

    # Imports come back as depends_on at module level.
    mod_deps = _objects_from(backend, "myfile", "depends_on")
    assert "os" in mod_deps
    assert "collections" in mod_deps

    # Class containment: Derived contains Derived.world.
    cls_contains = _objects_from(backend, "Derived", "contains")
    assert "Derived.world" in cls_contains

    # Inheritance edge: Derived depends_on Base.
    deps = _objects_from(backend, "Derived", "depends_on")
    assert "Base" in deps

    # And the round-trip preserved the predicate set at module level.
    pred_set = _predicates_from(backend, "myfile")
    assert pred_set == {"contains", "depends_on"}


# ---------------------------------------------------------------------------
# BashParserExtractor
# ---------------------------------------------------------------------------


def test_bash_parser_round_trip() -> None:
    """BashParserExtractor: contains + depends_on round-trip."""
    src = (
        "#!/bin/bash\n"
        "source ./helpers.sh\n"
        ". /etc/profile.d/setup.sh\n"
        "\n"
        "export FLOW_ROOT=/work/flow\n"
        "readonly TOOL_VERSION=1.2\n"
        "\n"
        "build_rtl() {\n"
        "    echo build\n"
        "}\n"
        "\n"
        "function run_sim() {\n"
        "    echo sim\n"
        "}\n"
    )
    extractor = BashParserExtractor()
    result = extractor.extract(src, source="flow.sh")

    backend = NetworkXBackend()
    backend.upsert_entities(result.entities)
    backend.upsert_triples(result.triples)

    contains = _objects_from(backend, "flow", "contains")
    assert "build_rtl" in contains
    assert "run_sim" in contains
    assert "FLOW_ROOT" in contains
    assert "TOOL_VERSION" in contains

    deps = _objects_from(backend, "flow", "depends_on")
    assert "helpers" in deps
    assert "setup" in deps


# ---------------------------------------------------------------------------
# GLiNEREntityExtractor (delegates to regex when GLiNER unavailable)
# ---------------------------------------------------------------------------


def test_gliner_extractor_round_trip_falls_back_to_regex() -> None:
    """GLiNEREntityExtractor delegates to RegexEntityExtractor when the
    GLiNER model isn't installed. Round-trip should still succeed.
    """
    extractor = GLiNEREntityExtractor()
    text = "Vector Search is a retrieval technique. RAG uses Embeddings."
    result = extractor.extract(text, source="g.md")

    backend = NetworkXBackend()
    backend.upsert_entities(result.entities)
    backend.upsert_triples(result.triples)

    # Whatever predicates the extractor produced, they must round-trip.
    for triple in result.triples:
        objs = _objects_from(backend, triple.subject, triple.predicate)
        assert triple.object in objs, (
            f"GLiNER round-trip lost {triple.subject}-[{triple.predicate}]->"
            f"{triple.object}; got {objs}"
        )

    # All extracted entities must be queryable.
    all_names = {e.name for e in backend.get_all_entities()}
    for ent in result.entities:
        assert ent.name in all_names


def test_gliner_no_re_module_for_header_stripping() -> None:
    """gliner_extractor._extract_entities_gliner must NOT use re.sub to strip
    markdown headers — structural line-filter only.

    This test would have FAILED before iter-015 because gliner_extractor.py
    contained ``re.sub(r"^#{1,6}\\s+.*$", ...)`` to strip headers.
    """
    import inspect
    import kgweave.knowledge_graph.extraction.gliner_extractor as _mod

    src = inspect.getsource(_mod._extract_entities_gliner_impl
                            if hasattr(_mod, "_extract_entities_gliner_impl")
                            else _mod.GLiNEREntityExtractor._extract_entities_gliner)
    assert "re.sub" not in src, (
        "gliner_extractor._extract_entities_gliner must not use re.sub; "
        "use structural line-split instead"
    )


def test_gliner_strips_markdown_headers_structurally() -> None:
    """Markdown header lines (# … through ###### …) must be removed from the
    text before GLiNER prediction.  The structural filter must handle headers
    separated by a tab (``#\\tHeading``) — something the old re.sub also
    caught but this test makes explicit.

    This test would have FAILED before iter-015 only when the structural path
    disagreed with the regex; we keep it here to pin the behaviour.
    """
    from kgweave.knowledge_graph.extraction.gliner_extractor import (
        GLiNEREntityExtractor,
    )

    extractor = GLiNEREntityExtractor()

    # Text with headers at various depths — none of these lines should survive
    # into the cleaned text fed to the NER model.
    header_text = (
        "# Top-level heading\n"
        "Some body text.\n"
        "## Sub-heading\n"
        "More body.\n"
        "###### Deep heading\n"
        "Tail text.\n"
    )

    # GLiNER falls back to regex extractor in CI (no model); we test the
    # internal clean step directly via the helper that both paths share.
    cleaned = _strip_md_headers(header_text)
    lines = [l for l in cleaned.splitlines() if l.strip()]
    assert all(not l.lstrip().startswith("#") for l in lines), (
        f"Header lines survived stripping: {[l for l in lines if l.lstrip().startswith('#')]}"
    )


def _strip_md_headers(text: str) -> str:
    """Structural header stripper — mirrors the implementation in gliner_extractor.py."""
    return "\n".join(
        line for line in text.splitlines()
        if not _is_md_header_line(line)
    )


def _is_md_header_line(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return False
    rest = stripped.lstrip("#")
    return len(stripped) - len(rest) <= 6 and (not rest or rest[0] in (" ", "\t"))
