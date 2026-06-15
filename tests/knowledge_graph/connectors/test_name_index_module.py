"""Verify the shared name-index module exposes its public surface and
that the connectors package still re-exports the previously-public
names (backwards compatibility for the public import surface).

v1.5-#3 pre-req: the 8-kind name-index logic used to live inline in
:class:`SvMarkdownReferenceConnector`. It now lives in
:mod:`knowledge_graph.connectors._name_index` so the upcoming Python
builder's connector can reuse it without duplication.
"""

from __future__ import annotations


def test_name_index_module_imports() -> None:
    """The new module exposes ``build_name_index`` and ``SV_INDEXED_KINDS``."""
    from knowledge_graph.connectors._name_index import (
        SV_INDEXED_KINDS,
        build_name_index,
    )

    assert callable(build_name_index)
    assert isinstance(SV_INDEXED_KINDS, tuple)
    # The original 8 kinds: module/package/typedef/forward-typedef +
    # ANSI/non-ANSI port (implicit/explicit each).
    assert len(SV_INDEXED_KINDS) == 8
    assert "SyntaxKind.ModuleDeclaration" in SV_INDEXED_KINDS


def test_public_connector_surface_unchanged() -> None:
    """Re-exports from ``knowledge_graph.connectors`` keep working."""
    from knowledge_graph.connectors import (  # noqa: F401
        Connector,
        SemanticSelfRefConnector,
        SvMarkdownReferenceConnector,
    )


def test_build_name_index_groups_by_corpus_and_name() -> None:
    """``build_name_index`` returns ``{corpus: {name: [id, ...]}}`` rows."""
    from knowledge_graph.connectors._name_index import build_name_index

    rows = [
        ("id1", "fifo", "demo"),
        ("id2", "fifo", "demo"),       # collision -> two ids under same name
        ("id3", "pkg_a", "demo"),
        ("id4", "fifo", "other"),      # same name in a different corpus
        ("id5", None, "demo"),          # nameless row -> skipped
        ("id6", "", "demo"),            # empty-string name -> skipped
    ]
    index = build_name_index(rows)

    assert set(index.keys()) == {"demo", "other"}
    assert sorted(index["demo"]["fifo"]) == ["id1", "id2"]
    assert index["demo"]["pkg_a"] == ["id3"]
    assert index["other"]["fifo"] == ["id4"]
