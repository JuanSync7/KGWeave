"""Slice S4 — Saved-query library (port the cone, keep the menu tiny).

Validable outcome: ``saved_query(graph, "cone_of_influence", target="fifo.count")``
returns a set equal to the Python ``cone_of_influence(graph, "fifo.count")``
projected to paths; the registry rejects an unknown query name with a typed
error (not a KeyError); the promotion bar (recurring AND not cleanly
expressible inline) is documented in the module docstring.

ANTI-CIRCULARITY: the Python ``cone_of_influence`` (flow.py) is the INDEPENDENT
TRUTH this test checks against. ``saved_query`` reproduces the result by an
independent Cypher/kuzu route — it must NOT import or delegate to flow.py. The
two independent implementations agreeing is the whole point. (Importing flow.py
HERE, in the test, is fine — the prohibition is on saved.py.)
"""

from __future__ import annotations

import glob
import inspect
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Graph fixture — same setup as test_cypher_core.py
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_CORPUS = sorted((_ROOT / "corpus").glob("*.sv"))


@pytest.fixture(scope="module")
def graph():
    from research.ast_experiment.src.build import build_kg

    g, _, _ = build_kg(_CORPUS)
    return g


def _paths_of_ids(g, ids) -> set[str]:
    """Project a set of node ids to the set of their semantic.path values."""
    by_id = {n["id"]: n for n in g["nodes"]}
    out: set[str] = set()
    for i in ids:
        node = by_id.get(i)
        if node is None:
            continue
        path = (node.get("semantic", {}) or {}).get("path")
        if path:
            out.add(path)
    return out


# ---------------------------------------------------------------------------
# EQUIVALENCE — the A/B Q3 truth: saved_query's independent Cypher cone agrees
# with the Python flow.py cone, projected to paths.
# ---------------------------------------------------------------------------


def test_saved_cone_equals_python_cone(graph):
    from research.ast_experiment.src.semantic import saved_query
    from research.ast_experiment.src.semantic.queries.flow import cone_of_influence

    truth = _paths_of_ids(graph, cone_of_influence(graph, "fifo.count"))
    got = set(saved_query(graph, "cone_of_influence", target="fifo.count").scalars())
    assert got == truth, f"saved cone {sorted(got)} != python cone {sorted(truth)}"


def test_saved_cone_is_non_trivial(graph):
    """The cone set is non-trivial (> 1 path) so an accidental empty==empty
    pass can't sneak through."""
    from research.ast_experiment.src.semantic import saved_query
    from research.ast_experiment.src.semantic.queries.flow import cone_of_influence

    truth = _paths_of_ids(graph, cone_of_influence(graph, "fifo.count"))
    assert len(truth) > 1, f"truth cone is trivial: {sorted(truth)}"
    got = set(saved_query(graph, "cone_of_influence", target="fifo.count").scalars())
    assert len(got) > 1, f"saved cone is trivial: {sorted(got)}"


# ---------------------------------------------------------------------------
# UNKNOWN NAME — typed SavedQueryError, NOT KeyError; names available queries /
# suggests a near-miss.
# ---------------------------------------------------------------------------


def test_unknown_query_name_raises_typed_error(graph):
    from research.ast_experiment.src.semantic import saved_query, SavedQueryError

    with pytest.raises(SavedQueryError) as exc_info:
        saved_query(graph, "no_such_query")

    err = exc_info.value
    # It must NOT be a KeyError.
    assert not isinstance(err, KeyError)
    # It names the unknown query.
    assert "no_such_query" in str(err)
    # It lists the available query names.
    assert "cone_of_influence" in str(err) or "cone_of_influence" in (err.available or [])


def test_unknown_query_name_suggests_near_miss(graph):
    from research.ast_experiment.src.semantic import saved_query, SavedQueryError

    with pytest.raises(SavedQueryError) as exc_info:
        saved_query(graph, "cone_of_influnce")  # typo near "cone_of_influence"

    err = exc_info.value
    assert err.suggestion == "cone_of_influence", (
        f"expected near-miss suggestion 'cone_of_influence', got {err.suggestion!r}"
    )


# ---------------------------------------------------------------------------
# LEAK — after several saved_query calls, no leaked kg_kuzu_* temp dirs.
# ---------------------------------------------------------------------------


def test_no_leaked_temp_dirs(graph):
    from research.ast_experiment.src.semantic import saved_query

    before = set(glob.glob(tempfile.gettempdir() + "/kg_kuzu_*"))
    for _ in range(3):
        saved_query(graph, "cone_of_influence", target="fifo.count")
    after = set(glob.glob(tempfile.gettempdir() + "/kg_kuzu_*"))
    leaked = after - before
    assert not leaked, f"saved_query leaked temp dirs: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# ANTI-CIRCULARITY GUARD — saved.py must NOT import flow.py's walk.
# ---------------------------------------------------------------------------


def test_saved_module_does_not_import_flow():
    """saved.py reproduces the cone independently — it must not import flow's
    Python walk (cone_of_influence / neighbors / find_drivers)."""
    import ast as _ast

    saved_path = (
        _ROOT / "src" / "semantic" / "queries" / "saved.py"
    )
    tree = _ast.parse(saved_path.read_text())
    imported: list[str] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom) and node.module:
            imported.append(node.module)
            for alias in node.names:
                imported.append(alias.name)
        elif isinstance(node, _ast.Import):
            for alias in node.names:
                imported.append(alias.name)
    bad = [
        i for i in imported
        if i.endswith("flow")
        or i in {"cone_of_influence", "neighbors", "find_drivers", "forward_cone"}
    ]
    assert not bad, f"saved.py imports flow's walk (circular): {bad}"


def test_promotion_bar_documented():
    """The promotion bar (recurring AND not cleanly expressible inline) is
    documented in saved.py's module docstring."""
    from research.ast_experiment.src.semantic.queries import saved as saved_mod

    doc = (saved_mod.__doc__ or "").lower()
    assert "recurring" in doc, "promotion bar must mention 'recurring'"
    assert "inline" in doc, "promotion bar must mention inline-expressibility"
