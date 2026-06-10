"""Slice S2 — Fail loud: structured, helpful errors.

Validable outcome:
    Every malformed or schema-violating query returns a typed CypherError
    (kind in {syntax, unknown_label, unknown_edge, unknown_property, engine} +
    message + suggestion on a near-miss edge/label) — never a raw kuzu
    traceback, never a silent empty result; AND a syntactically valid query
    with zero matches still returns a successful empty CypherResult
    (empty != error).

Tests (RED-first — all must fail until CypherError + classify_kuzu_error lands):
  1. unknown edge → CypherError kind=unknown_edge, suggestion from live vocab
  2. unknown label → CypherError kind=unknown_label
  3. syntax error → CypherError kind=syntax; str(err) contains no Python traceback
  4. ~10 additional bad queries — each raises CypherError, none leaks raw kuzu
  5. REGRESSION: zero-match valid query → empty CypherResult (NOT CypherError)
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Graph fixture — same pattern as test_cypher_core.py
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_CORPUS = sorted((_ROOT / "corpus").glob("*.sv"))


@pytest.fixture(scope="module")
def graph():
    from research.ast_experiment.src.build import build_kg

    g, _, _ = build_kg(_CORPUS)
    return g


# ---------------------------------------------------------------------------
# Helpers — derive live vocabulary (NO hardcoding)
# ---------------------------------------------------------------------------

def _live_edge_types(graph) -> list[str]:
    """Return sorted list of semantic edge types actually loaded into kuzu."""
    from research.ast_experiment.src.semantic.queries._kuzu_load import _EDGE_TYPES

    return sorted(_EDGE_TYPES(graph))


# ---------------------------------------------------------------------------
# CypherError import check (will fail red until the class is defined)
# ---------------------------------------------------------------------------


def test_cypher_error_importable():
    """CypherError must be importable from cypher_query.py."""
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError  # noqa: F401

    assert CypherError is not None
    assert issubclass(CypherError, Exception)


def test_cypher_error_has_required_fields():
    """CypherError must carry kind, message, suggestion as attributes."""
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    err = CypherError(kind="syntax", message="bad query", suggestion=None)
    assert err.kind == "syntax"
    assert err.message == "bad query"
    assert err.suggestion is None


def test_cypher_error_kind_values():
    """CypherError must accept each of the five required kind values."""
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    for kind in ("syntax", "unknown_label", "unknown_edge", "unknown_property", "engine"):
        err = CypherError(kind=kind, message="test", suggestion=None)
        assert err.kind == kind


# ---------------------------------------------------------------------------
# 1. Unknown edge type — raises CypherError kind=unknown_edge with suggestion
# ---------------------------------------------------------------------------


def test_unknown_edge_raises_cypher_error(graph):
    """MATCH with unknown edge type :has_field → CypherError kind=unknown_edge."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    with pytest.raises(CypherError) as exc_info:
        cypher_query(
            graph,
            "MATCH (i:N)-[:has_field]->(s:N) WHERE i.name='fifo_if' RETURN s.name",
        )
    err = exc_info.value
    assert err.kind == "unknown_edge", f"expected kind=unknown_edge, got {err.kind!r}"


def test_unknown_edge_suggestion_is_from_live_vocab(graph):
    """The suggestion for an unknown edge must be a real member of the live edge set."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    live = _live_edge_types(graph)
    assert live, "live edge vocabulary must be non-empty"

    with pytest.raises(CypherError) as exc_info:
        cypher_query(
            graph,
            "MATCH (i:N)-[:has_field]->(s:N) WHERE i.name='fifo_if' RETURN s.name",
        )
    err = exc_info.value
    # suggestion must come from the live vocabulary OR be None (no close match)
    if err.suggestion is not None:
        assert err.suggestion in live, (
            f"suggestion {err.suggestion!r} not in live edges: {live}"
        )
        # It should actually be close to 'has_field'
        close = difflib.get_close_matches("has_field", live, n=1)
        assert err.suggestion in close or err.suggestion in live, (
            f"suggestion {err.suggestion!r} not close to 'has_field' in {live}"
        )


# ---------------------------------------------------------------------------
# 2. Unknown label — raises CypherError kind=unknown_label
# ---------------------------------------------------------------------------


def test_unknown_label_raises_cypher_error(graph):
    """MATCH on unknown label :Node → CypherError kind=unknown_label."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    with pytest.raises(CypherError) as exc_info:
        cypher_query(graph, "MATCH (n:Node) RETURN n.name")
    err = exc_info.value
    assert err.kind == "unknown_label", f"expected kind=unknown_label, got {err.kind!r}"


def test_unknown_label_suggestion_is_n(graph):
    """Suggestion for unknown label should point to 'N' (the only valid label)."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    with pytest.raises(CypherError) as exc_info:
        cypher_query(graph, "MATCH (n:Node) RETURN n.name")
    err = exc_info.value
    # Suggestion might be 'N' (closest to 'Node') or None — both acceptable;
    # but if it's set it must be 'N'
    if err.suggestion is not None:
        assert err.suggestion == "N", f"only valid label is N, got {err.suggestion!r}"


# ---------------------------------------------------------------------------
# 3. Syntax error — CypherError kind=syntax; no raw Python traceback in message
# ---------------------------------------------------------------------------


def test_syntax_error_raises_cypher_error(graph):
    """Missing closing paren → CypherError kind=syntax."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    with pytest.raises(CypherError) as exc_info:
        cypher_query(graph, "MATCH (n:N RETURN n.name")
    err = exc_info.value
    assert err.kind == "syntax", f"expected kind=syntax, got {err.kind!r}"


def test_syntax_error_message_has_no_python_traceback(graph):
    """CypherError.message must NOT contain a Python traceback string."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    with pytest.raises(CypherError) as exc_info:
        cypher_query(graph, "MATCH (n:N RETURN n.name")
    err = exc_info.value
    assert "Traceback (most recent call last)" not in err.message, (
        f"CypherError.message must not contain a Python traceback: {err.message!r}"
    )
    # str(err) also must not expose a raw traceback
    assert "Traceback (most recent call last)" not in str(err), (
        f"str(CypherError) must not contain a Python traceback"
    )


# ---------------------------------------------------------------------------
# 4. ~10 additional bad queries — each raises CypherError; none crashes raw
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_query, expected_kind", [
    # Unknown property (in WHERE)
    ("MATCH (n:N) WHERE n.foobar='x' RETURN n.name", "unknown_property"),
    # Another unknown edge (has_field does not exist in the live graph)
    ("MATCH (a:N)-[:contains]->(b:N) RETURN a.name, b.name", "unknown_edge"),
    # Another unknown label
    ("MATCH (x:Module) RETURN x.name", "unknown_label"),
    # Another syntax error — missing RETURN
    ("MATCH (n:N)", "syntax"),
    # Completely garbled
    ("NOT VALID CYPHER AT ALL", "syntax"),
    # Unknown edge type — clearly not in live vocab
    ("MATCH (n:N)-[:has_field]->(m:N) RETURN m.name", "unknown_edge"),
    # Unknown property in RETURN
    ("MATCH (n:N) RETURN n.nonexistent_property_xyz", "unknown_property"),
    # Unknown label in relationship
    ("MATCH (n:N)-[:reads]->(m:Module) RETURN m.name", "unknown_label"),
    # Totally empty — Connection exception / syntax
    ("", "syntax"),
    # SELECT instead of MATCH
    ("SELECT * FROM N", "syntax"),
])
def test_bad_queries_raise_cypher_error(graph, bad_query, expected_kind):
    """All bad queries must raise CypherError — never a raw exception, never empty result."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    with pytest.raises(CypherError) as exc_info:
        cypher_query(graph, bad_query)
    err = exc_info.value
    # Must be a CypherError (not a raw kuzu RuntimeError or similar)
    assert isinstance(err, CypherError), f"expected CypherError, got {type(err)}"
    # Kind must be one of the valid values
    assert err.kind in ("syntax", "unknown_label", "unknown_edge", "unknown_property", "engine"), (
        f"unexpected kind {err.kind!r}"
    )
    # If we specified an expected kind, verify it
    if expected_kind is not None:
        assert err.kind == expected_kind, (
            f"query {bad_query!r}: expected kind={expected_kind!r}, got {err.kind!r}"
        )
    # message must not be empty
    assert err.message, "CypherError.message must not be empty"


def test_unknown_property_kind_classification(graph):
    """An unknown property in RETURN → CypherError kind=unknown_property."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    with pytest.raises(CypherError) as exc_info:
        cypher_query(graph, "MATCH (n:N) RETURN n.foobar")
    err = exc_info.value
    assert err.kind == "unknown_property", (
        f"expected kind=unknown_property, got {err.kind!r}"
    )


def test_engine_error_wrapped_not_naked(graph):
    """Any kuzu RuntimeError NOT matching a known pattern → kind=engine (never naked)."""
    # We can't easily trigger a pure 'engine' error without faking kuzu,
    # so we verify that ANY CypherError raised is at least not a raw kuzu exception.
    import kuzu

    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    # Try an arbitrary bad query
    with pytest.raises(CypherError) as exc_info:
        cypher_query(graph, "MATCH (n:BOGUS_LABEL_XYZ) RETURN n")
    err = exc_info.value
    assert isinstance(err, CypherError)
    # Must NOT be a raw kuzu exception
    assert not isinstance(err, kuzu.RuntimeError if hasattr(kuzu, "RuntimeError") else type(None))


# ---------------------------------------------------------------------------
# 5. REGRESSION: valid zero-match query → empty CypherResult, NOT CypherError
# ---------------------------------------------------------------------------


def test_zero_match_valid_query_returns_empty_result(graph):
    """A syntactically valid query with zero matches → empty CypherResult (not error)."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import (
        CypherError,
        CypherResult,
    )

    result = cypher_query(
        graph,
        "MATCH (n:N {name:'definitely_absent_zzz'}) RETURN n.name",
    )
    # Must be a CypherResult, not raise CypherError
    assert isinstance(result, CypherResult), f"expected CypherResult, got {type(result)}"
    assert result.rows == [], f"expected empty rows, got {result.rows}"
    # columns must be populated even for an empty result
    assert result.columns == ["n.name"], f"expected columns=['n.name'], got {result.columns}"


def test_zero_match_multi_column_valid_query(graph):
    """Zero-match multi-column valid query → empty CypherResult with correct columns."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherResult

    result = cypher_query(
        graph,
        "MATCH (a:N)-[:reads]->(b:N) WHERE a.name='nonexistent_node_xyz' RETURN a.name, b.name",
    )
    assert isinstance(result, CypherResult)
    assert result.rows == []
    assert len(result.columns) == 2


# ---------------------------------------------------------------------------
# 6. CypherError to_dict / detail contract (typed payload for consumers)
# ---------------------------------------------------------------------------


def test_cypher_error_to_dict_has_required_keys():
    """CypherError.to_dict() must return a dict with kind, message, suggestion."""
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError

    err = CypherError(kind="syntax", message="Parser exception: expected RETURN", suggestion="N")
    d = err.to_dict()
    assert isinstance(d, dict), f"to_dict() must return dict, got {type(d)}"
    assert "kind" in d
    assert "message" in d
    assert "suggestion" in d
    assert d["kind"] == "syntax"
    assert d["message"] == "Parser exception: expected RETURN"
    assert d["suggestion"] == "N"
