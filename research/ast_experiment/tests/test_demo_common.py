"""Unit tests pinning the contract of ``scripts._demo_common``.

v1.3-#3 promotes the bucket-1 categoriser and ``RULE_FAMILIES`` table out
of the two demo-graph exporters into a single module. These tests pin
the contract so future drift between the two exporters is impossible:
both must import the same symbols, and the shape of those symbols is
covered here.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from scripts import _demo_common

_HERE = Path(__file__).resolve().parent.parent
BUCKET1_PATH = _HERE / "BUCKET_1_CHECKLIST.md"


# --------------------------------------------------------------------------- #
# Bucket-1 categoriser                                                        #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def bucket1() -> dict[str, str]:
    return _demo_common.parse_bucket1_categories(BUCKET1_PATH)


def test_parse_bucket1_returns_non_empty_map(bucket1: dict[str, str]) -> None:
    """Parser yields at least one row per category for the real checklist."""
    assert bucket1, "bucket1 map must not be empty"
    cats = set(bucket1.values())
    # SPEC §3.3 acknowledges three positive categories on top of token/semantic.
    assert {"semantic", "structural", "blob"}.issubset(cats)


def test_parse_bucket1_categories_are_legal(bucket1: dict[str, str]) -> None:
    """No surprise category strings leak out of the parser."""
    legal = {"semantic", "structural", "blob"}
    for kind, cat in bucket1.items():
        assert cat in legal, f"unexpected category {cat!r} for kind {kind!r}"


def test_category_for_kind_branches(bucket1: dict[str, str]) -> None:
    """Tokens, semantic flags, bucket-1 hits, and fallbacks all route correctly."""
    # Token short-circuit beats everything (kind irrelevant).
    assert (
        _demo_common.category_for_kind(
            bucket1, kind="Identifier", is_token=True, is_semantic=False
        )
        == "token"
    )
    # Semantic flag beats bucket-1.
    assert (
        _demo_common.category_for_kind(
            bucket1, kind="SyntaxList", is_token=False, is_semantic=True
        )
        == "semantic"
    )
    # Unknown kind falls back to "structural".
    assert (
        _demo_common.category_for_kind(
            bucket1, kind="CompilationUnit", is_token=False, is_semantic=False
        )
        == "structural"
    )
    # At least one real bucket-1 entry resolves to its mapped category.
    sample_kind, sample_cat = next(iter(bucket1.items()))
    assert (
        _demo_common.category_for_kind(
            bucket1, kind=sample_kind, is_token=False, is_semantic=False
        )
        == sample_cat
    )


# --------------------------------------------------------------------------- #
# RULE_FAMILIES table                                                         #
# --------------------------------------------------------------------------- #


def test_rule_families_shape() -> None:
    """Every entry has the documented shape and rule-id pattern."""
    fams = _demo_common.RULE_FAMILIES
    assert isinstance(fams, list) and fams, "RULE_FAMILIES must be a non-empty list"
    rid_pat = re.compile(r"^S\d+[a-z]?$")
    ids: set[str] = set()
    for fam in fams:
        assert set(fam) >= {"id", "title", "ruleIds", "blurb"}
        assert isinstance(fam["id"], str) and fam["id"]
        assert fam["id"] not in ids, f"duplicate family id {fam['id']!r}"
        ids.add(fam["id"])
        assert isinstance(fam["ruleIds"], list) and fam["ruleIds"], fam["id"]
        for rid in fam["ruleIds"]:
            assert rid_pat.match(rid), f"bad rule id {rid!r} in family {fam['id']}"


def test_attribute_to_family_resolves_via_semantic_payload() -> None:
    """A semantic.ruleId on the node beats the static kind map."""
    node = {"kind": "ModuleDeclarationSyntax", "semantic": {"ruleId": "S4"}}
    rid, fam = _demo_common.attribute_to_family(node, kind_to_rule={})
    assert rid == "S4"
    assert fam == "nets_vars"


def test_attribute_to_family_resolves_via_kind_map() -> None:
    """When no semantic payload exists the kind→rule map is consulted."""
    node = {"kind": "SyntaxKind.ModuleDeclaration"}
    rid, fam = _demo_common.attribute_to_family(
        node, kind_to_rule={"SyntaxKind.ModuleDeclaration": "S1"}
    )
    assert rid == "S1"
    # S1 lives in two families (structure + ports_params) — pick the first.
    assert fam == "structure"


def test_attribute_to_family_returns_none_when_unknown() -> None:
    node = {"kind": "SomethingObscure"}
    assert _demo_common.attribute_to_family(node, kind_to_rule={}) == (None, None)


# --------------------------------------------------------------------------- #
# Importability smoke (the deduplication contract)                            #
# --------------------------------------------------------------------------- #


def test_both_exporters_import_shared_module() -> None:
    """Both demo exporters must source the shared symbols from _demo_common.

    The whole point of v1.3-#3 is to make drift between the two scripts
    structurally impossible. We assert symbol identity (``is``) rather
    than equality.
    """
    legacy = importlib.import_module("scripts.export_demo_graph")
    kuzu = importlib.import_module("scripts.export_demo_graph_kuzu")
    assert legacy.RULE_FAMILIES is _demo_common.RULE_FAMILIES
    assert kuzu.RULE_FAMILIES is _demo_common.RULE_FAMILIES
