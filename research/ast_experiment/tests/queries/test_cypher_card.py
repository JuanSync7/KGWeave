"""Slice S3 — generated, drift-proof schema card.

Tests:
1. bidirectional no-drift: parsed_card_edges == live_edges(graph) AND
   parsed_card_roles == live_roles(graph) (set equality — missing OR extra fails).
2. recipe execution: each Cypher recipe from the card executes without CypherError.
3. determinism: two generator runs → byte-identical output.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Helper: parse edge names from the card markdown
# ---------------------------------------------------------------------------

def _is_identifier(tok: str) -> bool:
    """Return True if tok looks like a plain identifier (a-z, 0-9, underscore only)."""
    if not tok:
        return False
    return all(c.isalnum() or c == "_" for c in tok) and not tok[0].isdigit()


def _extract_identifiers_from_list_line(line: str) -> list[str]:
    """Extract backtick-quoted identifiers from a line that is purely an item list.

    The generator emits vocabulary lists as lines of the form:
        `foo`, `bar`, `baz`.

    Such lines start with a backtick after stripping. We only extract from these
    lines — not from prose lines that happen to contain backtick-quoted text.
    """
    stripped = line.strip()
    # Only process lines that start with a backtick (list lines, not prose)
    if not stripped.startswith("`"):
        return []
    parts = stripped.split("`")
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # odd index = inside backticks
            tok = part.strip().rstrip(".,;")
            if _is_identifier(tok):
                result.append(tok)
    return result


def _parse_card_edges(card_text: str) -> set[str]:
    """Extract identifier-style relationship names from the EDGES section.

    Only collects from list lines (lines starting with a backtick) — excludes
    prose, sub-headers, Cypher examples, etc.
    """
    in_edges_section = False
    edges: set[str] = set()
    for line in card_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and "edge" in stripped.lower():
            in_edges_section = True
            continue
        if stripped.startswith("## ") and in_edges_section:
            in_edges_section = False
            continue
        if in_edges_section:
            for tok in _extract_identifiers_from_list_line(line):
                edges.add(tok)
    return edges


def _parse_card_roles(card_text: str) -> set[str]:
    """Extract identifier-style role names from the ROLES section.

    Only collects from table cells that contain backtick-quoted identifiers.
    The generator emits roles in a markdown table: | **Family** | `role1`, `role2` |
    """
    in_roles_section = False
    roles: set[str] = set()
    for line in card_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and "role" in stripped.lower():
            in_roles_section = True
            continue
        if stripped.startswith("## ") and in_roles_section:
            in_roles_section = False
            continue
        if in_roles_section:
            # Roles are in table rows: | **Family** | `r1`, `r2`, ... |
            if not stripped.startswith("|"):
                continue
            # Split into table cells
            cells = stripped.split("|")
            # cells[0] is empty (before leading |), cells[-1] is empty (after trailing |)
            for cell in cells[1:-1]:
                cell = cell.strip()
                # Second column: role list
                parts = cell.split("`")
                for i, part in enumerate(parts):
                    if i % 2 == 1:
                        tok = part.strip().rstrip(".,;")
                        if _is_identifier(tok):
                            roles.add(tok)
    return roles


def _parse_card_recipes(card_text: str) -> list[str]:
    """Extract all Cypher queries from fenced code blocks inside the RECIPES section."""
    in_recipes_section = False
    in_fence = False
    recipes: list[str] = []
    current: list[str] = []
    for line in card_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and "recipe" in stripped.lower():
            in_recipes_section = True
            continue
        if stripped.startswith("## ") and in_recipes_section:
            in_recipes_section = False
            continue
        if in_recipes_section:
            if stripped.startswith("```") and not in_fence:
                in_fence = True
                current = []
                continue
            if stripped.startswith("```") and in_fence:
                in_fence = False
                recipe = "\n".join(current).strip()
                if recipe:
                    recipes.append(recipe)
                current = []
                continue
            if in_fence:
                current.append(line)
    return recipes


# ---------------------------------------------------------------------------
# Test 1 — no-drift: card edges == live edges
# ---------------------------------------------------------------------------

def test_card_edges_match_live_vocab(graph):
    """Parsed card edges == live_edges(graph); missing OR extra → fail."""
    from research.ast_experiment.scripts.gen_cypher_card import (
        generate_card,
        live_edges,
    )

    card_text = generate_card(graph)
    parsed = _parse_card_edges(card_text)
    live = set(live_edges(graph))
    missing = live - parsed
    extra = parsed - live
    assert not missing, f"edges in live vocab but missing from card: {sorted(missing)}"
    assert not extra, f"edges in card but NOT in live vocab: {sorted(extra)}"


# ---------------------------------------------------------------------------
# Test 2 — no-drift: card roles == live roles
# ---------------------------------------------------------------------------

def test_card_roles_match_live_vocab(graph):
    """Parsed card roles == live_roles(graph); missing OR extra → fail."""
    from research.ast_experiment.scripts.gen_cypher_card import (
        generate_card,
        live_roles,
    )

    card_text = generate_card(graph)
    parsed = _parse_card_roles(card_text)
    live = set(live_roles(graph))
    missing = live - parsed
    extra = parsed - live
    assert not missing, f"roles in live vocab but missing from card: {sorted(missing)}"
    assert not extra, f"roles in card but NOT in live vocab: {sorted(extra)}"


# ---------------------------------------------------------------------------
# Test 3 — recipe execution: all recipes parse + execute without CypherError
# ---------------------------------------------------------------------------

def test_card_recipes_execute(graph):
    """Every Cypher recipe in the card executes without CypherError."""
    from research.ast_experiment.src.semantic import cypher_query
    from research.ast_experiment.src.semantic.queries.cypher_query import CypherError
    from research.ast_experiment.scripts.gen_cypher_card import generate_card

    card_text = generate_card(graph)
    recipes = _parse_card_recipes(card_text)
    assert recipes, "no recipes found in card — card is malformed"

    for recipe in recipes:
        try:
            result = cypher_query(graph, recipe)
            # result must be a CypherResult — no exception means success
            assert result is not None, f"recipe returned None: {recipe!r}"
        except CypherError as e:
            pytest.fail(f"CypherError executing recipe:\n{recipe!r}\nError: {e}")


# ---------------------------------------------------------------------------
# Test 4 — determinism: two runs → byte-identical
# ---------------------------------------------------------------------------

def test_card_generation_is_deterministic(graph):
    """Two calls to generate_card() with the same graph → byte-identical."""
    from research.ast_experiment.scripts.gen_cypher_card import generate_card

    run1 = generate_card(graph)
    run2 = generate_card(graph)
    assert run1 == run2, (
        "generate_card() is not deterministic — output differs between calls"
    )


# ---------------------------------------------------------------------------
# Test 5 — written file is byte-identical to generate_card() output
# ---------------------------------------------------------------------------

def test_card_file_matches_generated(graph):
    """docs/card_cypher.md exists and matches generate_card() output exactly."""
    from research.ast_experiment.scripts.gen_cypher_card import generate_card

    card_path = _ROOT / "docs" / "card_cypher.md"
    assert card_path.exists(), f"card_cypher.md not found at {card_path}"
    on_disk = card_path.read_text(encoding="utf-8")
    generated = generate_card(graph)
    assert on_disk == generated, (
        "docs/card_cypher.md is stale — re-run scripts/gen_cypher_card.py to regenerate"
    )
