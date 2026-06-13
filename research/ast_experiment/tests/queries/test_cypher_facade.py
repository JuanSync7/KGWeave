"""Slice S5 — Typed facade + core dependency (RagWeave contract).

Validable outcome: kuzu is declared a CORE dependency in pyproject; the
semantic facade exports cypher_query, saved_query, CypherResult, CypherError
such that a consumer needs no internal-module imports; CypherResult and
CypherError round-trip through Pydantic model_validate / model_dump.

All imports in this module go through the facade only — no internal-module
imports from ``...queries._kuzu_load`` or other private paths.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Graph fixture (same pattern as test_cypher_core.py)
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_CORPUS = sorted((_ROOT / "corpus").glob("*.sv"))


@pytest.fixture(scope="module")
def graph():
    from research.ast_experiment.src.build import build_kg

    g, _, _ = build_kg(_CORPUS)
    return g


# ---------------------------------------------------------------------------
# 1. Facade import contract — all five names importable from the facade
# ---------------------------------------------------------------------------


def test_facade_exports_cypher_query():
    """cypher_query is importable from the semantic facade."""
    from research.ast_experiment.src.semantic import cypher_query  # noqa: F401

    assert callable(cypher_query)


def test_facade_exports_saved_query():
    """saved_query is importable from the semantic facade."""
    from research.ast_experiment.src.semantic import saved_query  # noqa: F401

    assert callable(saved_query)


def test_facade_exports_cypher_result():
    """CypherResult is importable from the semantic facade."""
    from research.ast_experiment.src.semantic import CypherResult  # noqa: F401

    assert issubclass(CypherResult, BaseModel)


def test_facade_exports_cypher_error():
    """CypherError is importable from the semantic facade — NEW in S5."""
    from research.ast_experiment.src.semantic import CypherError  # noqa: F401

    assert issubclass(CypherError, Exception)


def test_facade_exports_semantic_node():
    """SemanticNode is importable from the semantic facade — NEW in S5."""
    from research.ast_experiment.src.semantic import SemanticNode  # noqa: F401

    assert issubclass(SemanticNode, BaseModel)


def test_facade_all_contains_cypher_error():
    """CypherError appears in the facade's __all__."""
    import research.ast_experiment.src.semantic as sem

    assert "CypherError" in sem.__all__, (
        f"CypherError missing from facade __all__: {sem.__all__}"
    )


def test_facade_all_contains_semantic_node():
    """SemanticNode appears in the facade's __all__."""
    import research.ast_experiment.src.semantic as sem

    assert "SemanticNode" in sem.__all__, (
        f"SemanticNode missing from facade __all__: {sem.__all__}"
    )


def test_no_internal_import_needed():
    """Consumer can use CypherError and SemanticNode without any internal import.

    This is a documentation-style assertion: we verify that the names are
    present on the facade module object, meaning no consumer ever needs to
    reach into ``...queries.cypher_query`` or ``..._cypher_validate``.
    """
    import research.ast_experiment.src.semantic as sem

    for name in ("cypher_query", "saved_query", "CypherResult", "CypherError", "SemanticNode"):
        assert hasattr(sem, name), f"facade missing {name!r}"


# ---------------------------------------------------------------------------
# 2. CypherResult Pydantic round-trip
# ---------------------------------------------------------------------------


def test_cypher_result_round_trip():
    """CypherResult round-trips through model_validate / model_dump."""
    from research.ast_experiment.src.semantic import CypherResult

    original = CypherResult(
        columns=["name", "role"],
        rows=[{"name": "fifo", "role": "module"}, {"name": "clk", "role": "port"}],
    )
    dumped = original.model_dump()
    restored = CypherResult.model_validate(dumped)
    assert restored.columns == original.columns
    assert restored.rows == original.rows


def test_cypher_result_empty_round_trip():
    """Empty CypherResult also round-trips cleanly."""
    from research.ast_experiment.src.semantic import CypherResult

    original = CypherResult(columns=["id"], rows=[])
    restored = CypherResult.model_validate(original.model_dump())
    assert restored.columns == ["id"]
    assert restored.rows == []


# ---------------------------------------------------------------------------
# 3. CypherError Pydantic round-trip (via to_dict() + a typed view model)
# ---------------------------------------------------------------------------


class _CypherErrorView(BaseModel):
    """Pydantic view of the typed CypherError payload for round-trip testing."""

    kind: str
    message: str
    suggestion: str | None = None


def test_cypher_error_round_trip_via_to_dict():
    """CypherError's typed payload (to_dict) round-trips through a Pydantic model.

    CypherError is an Exception subclass, not itself a BaseModel.  Its
    ``to_dict()`` method exposes the structured payload.  We validate that
    dict into a Pydantic model and round-trip it — satisfying the slice
    outcome's 'model_validate / model_dump' requirement for CypherError.
    """
    from research.ast_experiment.src.semantic import CypherError

    err = CypherError(kind="syntax", message="unexpected token ';'", suggestion=None)
    dumped = err.to_dict()
    view = _CypherErrorView.model_validate(dumped)
    restored_dict = view.model_dump()
    assert restored_dict["kind"] == "syntax"
    assert restored_dict["message"] == "unexpected token ';'"
    assert restored_dict["suggestion"] is None


def test_cypher_error_with_suggestion_round_trip():
    """CypherError with a suggestion round-trips cleanly."""
    from research.ast_experiment.src.semantic import CypherError

    err = CypherError(kind="unknown_label", message="Table X does not exist", suggestion="N")
    view = _CypherErrorView.model_validate(err.to_dict())
    restored = view.model_dump()
    assert restored["kind"] == "unknown_label"
    assert restored["suggestion"] == "N"


def test_cypher_error_round_trip_field_equality():
    """model_validate(to_dict()) == reconstructed CypherError fields."""
    from research.ast_experiment.src.semantic import CypherError

    for kind in ("syntax", "unknown_label", "unknown_edge", "unknown_property", "engine"):
        err = CypherError(kind=kind, message=f"test {kind}", suggestion="hint")
        view = _CypherErrorView.model_validate(err.to_dict())
        assert view.kind == err.kind
        assert view.message == err.message
        assert view.suggestion == err.suggestion


# ---------------------------------------------------------------------------
# 4. SemanticNode Pydantic round-trip
# ---------------------------------------------------------------------------


def test_semantic_node_round_trip():
    """SemanticNode round-trips through model_validate / model_dump."""
    from research.ast_experiment.src.semantic import SemanticNode

    original = SemanticNode(
        id="fifo.clk",
        role="port",
        name="clk",
        path="fifo.clk",
        attributes={"direction": "input", "width": 1},
    )
    dumped = original.model_dump()
    restored = SemanticNode.model_validate(dumped)
    assert restored.id == original.id
    assert restored.role == original.role
    assert restored.attributes == original.attributes


def test_semantic_node_minimal_round_trip():
    """SemanticNode with defaults round-trips cleanly."""
    from research.ast_experiment.src.semantic import SemanticNode

    original = SemanticNode(id="x")
    restored = SemanticNode.model_validate(original.model_dump())
    assert restored.id == "x"
    assert restored.role is None
    assert restored.attributes == {}


# ---------------------------------------------------------------------------
# 5. kuzu declared as CORE dependency in root pyproject.toml
# ---------------------------------------------------------------------------

_PYPROJECT_PATH = Path(__file__).resolve().parents[4] / "pyproject.toml"


def test_kuzu_declared_in_root_pyproject():
    """kuzu appears by name in [project].dependencies (core list) of root pyproject.toml."""
    assert _PYPROJECT_PATH.exists(), f"root pyproject.toml not found at {_PYPROJECT_PATH}"
    with open(_PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    core_deps: list[str] = data.get("project", {}).get("dependencies", [])
    # Each dep is a PEP 508 string like "kuzu>=0.11"; check the name part
    kuzu_found = any(
        dep.lower().startswith("kuzu") for dep in core_deps
    )
    assert kuzu_found, (
        f"'kuzu' not found in [project].dependencies (core) of {_PYPROJECT_PATH}.\n"
        f"Core deps: {core_deps}"
    )


def test_kuzu_not_only_in_optional():
    """kuzu must be in core deps, not buried only in optional-dependencies."""
    with open(_PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    core_deps: list[str] = data.get("project", {}).get("dependencies", [])
    kuzu_in_core = any(dep.lower().startswith("kuzu") for dep in core_deps)
    assert kuzu_in_core, "kuzu must be in core [project].dependencies, not only optional"
