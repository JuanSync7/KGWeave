"""Guard test for S7 — the graph_query DSL is retired (Cypher-only cutover).

The pattern-walker ``graph_query`` (plus its synthetic ``contains`` edge and
``_edge_type_matches`` helper) is DELETED. The sole query surface is now Cypher
(``cypher_query`` / ``saved_query``) plus the kept Python oracles
(``neighbors`` / ``find_by_name`` / cones) and the promoted-node generator
``queryable_nodes``.

This test pins the cutover:

  * ``graph_query`` is NOT importable from either the facade or the module path.
  * ``queryable_nodes`` IS still importable from the facade (it was relocated to
    connectivity.py — it is NOT the DSL) and still yields the promoted nodes.
  * No remaining ``.py`` file under src/ or tests/ IMPORTS ``graph_query``
    (comments/data mentioning the word are fine; imports are not).

NO regex anywhere — the structural scan uses plain string operations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_EXPERIMENT_DIR = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = _EXPERIMENT_DIR / "src"
_TESTS_DIR = _EXPERIMENT_DIR / "tests"


def test_graph_query_not_importable_from_facade():
    """graph_query must NOT be importable from the public facade."""
    with pytest.raises(ImportError):
        from research.ast_experiment.src.semantic import graph_query  # noqa: F401


def test_graph_query_module_path_gone():
    """The graph_query module file is deleted (ModuleNotFoundError on import)."""
    with pytest.raises(ModuleNotFoundError):
        import research.ast_experiment.src.semantic.queries.graph_query  # noqa: F401


def test_queryable_nodes_still_importable_and_works():
    """REGRESSION: queryable_nodes survived the relocation to connectivity.py.

    It is still importable at the same facade path and, given a built graph,
    yields exactly the promoted (queryable) nodes.
    """
    from research.ast_experiment.src.semantic import queryable_nodes
    from research.ast_experiment.src.build import build_kg

    corpus = sorted((_EXPERIMENT_DIR / "corpus").glob("*.sv"))
    graph, _, _ = build_kg(corpus)

    promoted = list(queryable_nodes(graph))
    assert promoted, "expected at least one promoted node"
    # Every yielded node carries the queryable flag.
    assert all(n.get("queryable") for n in promoted)
    # And it matches the raw filter over graph['nodes'].
    expected = [n for n in graph["nodes"] if n.get("queryable")]
    assert {n["id"] for n in promoted} == {n["id"] for n in expected}


def _imports_graph_query(line: str) -> bool:
    """True if a source line IMPORTS graph_query (not a mere mention).

    Plain string ops only — no regex. An import line is one that mentions
    ``graph_query`` and also contains the ``import`` keyword as part of an
    import statement (``from ... import ...`` or ``import ...``).
    """
    stripped = line.strip()
    if "graph_query" not in stripped:
        return False
    if "import" not in stripped:
        return False
    # A comment that merely talks about graph_query is fine even if the word
    # "import" appears in prose — exclude full-line comments.
    if stripped.startswith("#"):
        return False
    # Must be an actual import statement form.
    if stripped.startswith("from ") and " import " in stripped:
        return True
    if stripped.startswith("import "):
        return True
    return False


def test_no_residual_graph_query_imports():
    """STRUCTURAL: no .py file under src/ or tests/ imports graph_query.

    The deleted module file itself is excluded (it should be gone, but guard
    against a stale copy). Comments and data that merely mention the word are
    permitted — only IMPORT statements are forbidden.
    """
    deleted_module = _SRC_DIR / "semantic" / "queries" / "graph_query.py"
    # This guard test itself deliberately *attempts* the (now-failing) imports
    # inside ``pytest.raises`` blocks to prove they no longer resolve — exclude
    # it so its intentional import lines don't read as residual imports.
    this_file = Path(__file__).resolve()
    offenders: list[str] = []
    for base in (_SRC_DIR, _TESTS_DIR):
        for p in base.rglob("*.py"):
            if p == deleted_module or p.resolve() == this_file:
                continue
            for lineno, line in enumerate(p.read_text().splitlines(), start=1):
                if _imports_graph_query(line):
                    offenders.append(f"{p}:{lineno}: {line.strip()}")
    assert not offenders, f"residual graph_query imports: {offenders}"
