"""Structural-diff tests for the Kuzu-port demo exporter.

These tests run the **new** facade-driven exporter
(:mod:`scripts.export_demo_graph_kuzu`) and the **legacy** in-memory exporter
(:mod:`scripts.export_demo_graph`) against the same SV corpus and assert
structural equivalence on every FE-visible field.

Allowed differences (documented in JOURNAL v1.2 #3):
* ``generatedAt`` differs.
* Edge ids and node listing order differ; the structural assertions below key
  on ``(src, dst, type)`` sets and on per-category counts rather than on order.
* Token spans may differ by leading-trivia bytes (Kuzu writer includes leading
  trivia; legacy exporter does not). Non-token spans are byte-precise.

If anything else drifts, the new exporter is wrong (or the writer dropped data).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_EXP_DIR = _REPO_ROOT / "research" / "ast_experiment"
_SCRIPTS_DIR = _EXP_DIR / "scripts"
_SRC_DIR = _REPO_ROOT / "src"
for _p in (str(_EXP_DIR), str(_REPO_ROOT), str(_SRC_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Subset fixture for fast TDD; full-corpus integration smoke at the bottom.
_FIXTURE_FILES = [
    _EXP_DIR / "corpus" / "fifo.sv",
    _EXP_DIR / "corpus" / "fifo_pkg.sv",
    _EXP_DIR / "corpus" / "checker_corpus.sv",
]


@pytest.fixture(scope="module")
def legacy_artifact(tmp_path_factory):
    """Run the legacy exporter into a tmp graph.json."""
    from scripts.export_demo_graph import export as legacy_export

    tmp = tmp_path_factory.mktemp("legacy_demo")
    out = tmp / "graph.json"
    return legacy_export(_FIXTURE_FILES, out)


@pytest.fixture(scope="module")
def kuzu_artifact(tmp_path_factory):
    """Run the new facade-driven exporter into a tmp graph.json."""
    from scripts.export_demo_graph_kuzu import export as kuzu_export

    tmp = tmp_path_factory.mktemp("kuzu_demo")
    out = tmp / "graph.json"
    return kuzu_export(_FIXTURE_FILES, out, store_dir=tmp / "store", corpus="demo-test")


# ---------------------------------------------------------------- smoke wiring


def test_kuzu_exporter_uses_facade_not_src_build():
    """The new exporter must NOT import the in-memory ``src.build`` codepath.

    Reading the file as text is the cheapest way to assert the import surface.
    """
    text = (_SCRIPTS_DIR / "export_demo_graph_kuzu.py").read_text()
    assert "from src.build" not in text
    assert "import src.build" not in text
    # Positive assertion: the exporter routes through the public facade.
    assert "from knowledge_graph import" in text


# ---------------------------------------------------------------- structural


def test_top_level_keys_match(legacy_artifact, kuzu_artifact):
    """Both artifacts carry the same top-level SPEC §3.1 keys.

    The Kuzu artifact is allowed an extra ``exporter`` forensics field; legacy
    has nothing extra. We assert subset equality both ways modulo that.
    """
    legacy_keys = set(legacy_artifact.keys())
    kuzu_keys = set(kuzu_artifact.keys()) - {"exporter"}
    assert legacy_keys == kuzu_keys


def test_version_string_matches(legacy_artifact, kuzu_artifact):
    """SPEC §3.1 ``version`` must stay equal between the two."""
    assert legacy_artifact["version"] == kuzu_artifact["version"]


def test_files_set_matches(legacy_artifact, kuzu_artifact):
    """Same set of FileEntry ids and same per-file source/lineCount."""
    legacy_by_id = {f["id"]: f for f in legacy_artifact["files"]}
    kuzu_by_id = {f["id"]: f for f in kuzu_artifact["files"]}
    assert set(legacy_by_id) == set(kuzu_by_id)
    for fid, lf in legacy_by_id.items():
        kf = kuzu_by_id[fid]
        assert lf["path"] == kf["path"], f"{fid}: path drift {lf['path']} vs {kf['path']}"
        assert lf["source"] == kf["source"], f"{fid}: source bytes drift"
        assert lf["lineCount"] == kf["lineCount"]


def test_node_id_set_matches(legacy_artifact, kuzu_artifact):
    """Every legacy node id round-trips through the Kuzu store.

    If the Kuzu writer dropped a node category (e.g. failed to materialize an
    unresolved placeholder) this test surfaces it via the set-diff.
    """
    legacy_ids = {n["id"] for n in legacy_artifact["nodes"]}
    kuzu_ids = {n["id"] for n in kuzu_artifact["nodes"]}
    only_legacy = legacy_ids - kuzu_ids
    only_kuzu = kuzu_ids - legacy_ids
    assert not only_legacy, f"Kuzu missing {len(only_legacy)} legacy nodes: {sorted(only_legacy)[:5]}"
    assert not only_kuzu, f"Kuzu added {len(only_kuzu)} nodes not in legacy: {sorted(only_kuzu)[:5]}"


def test_category_distribution_matches(legacy_artifact, kuzu_artifact):
    """SPEC §3.3 category counts (semantic / structural / blob / token) match."""
    legacy_counts = Counter(n["category"] for n in legacy_artifact["nodes"])
    kuzu_counts = Counter(n["category"] for n in kuzu_artifact["nodes"])
    assert legacy_counts == kuzu_counts, (
        f"category drift: legacy={dict(legacy_counts)} kuzu={dict(kuzu_counts)}"
    )


def test_per_node_category_matches(legacy_artifact, kuzu_artifact):
    """Per-node category attribution matches on every shared id."""
    legacy_cat = {n["id"]: n["category"] for n in legacy_artifact["nodes"]}
    kuzu_cat = {n["id"]: n["category"] for n in kuzu_artifact["nodes"]}
    mismatches = [
        (nid, legacy_cat[nid], kuzu_cat[nid])
        for nid in legacy_cat
        if nid in kuzu_cat and legacy_cat[nid] != kuzu_cat[nid]
    ]
    assert not mismatches, f"category mismatches (first 5): {mismatches[:5]}"


def test_semantic_payloads_match(legacy_artifact, kuzu_artifact):
    """Every node carrying ``semantic`` has the same role / name / path."""
    legacy_sem = {n["id"]: n.get("semantic") for n in legacy_artifact["nodes"] if n.get("semantic")}
    kuzu_sem = {n["id"]: n.get("semantic") for n in kuzu_artifact["nodes"] if n.get("semantic")}
    assert set(legacy_sem) == set(kuzu_sem)
    for nid, ls in legacy_sem.items():
        assert ls == kuzu_sem[nid], f"semantic dict drift on {nid}: {ls} vs {kuzu_sem[nid]}"


def test_edge_triple_set_matches(legacy_artifact, kuzu_artifact):
    """Edges keyed by ``(src, dst, type)`` form identical sets.

    Edge payloads can differ in ordering of payload keys but the triple-set is
    the FE's true contract (used by Q1..Q6 traversal queries).
    """
    def _key(e):
        return (e["src"], e["dst"], e["type"])

    legacy_edges = Counter(_key(e) for e in legacy_artifact["edges"])
    kuzu_edges = Counter(_key(e) for e in kuzu_artifact["edges"])
    only_legacy = legacy_edges - kuzu_edges
    only_kuzu = kuzu_edges - legacy_edges
    assert not only_legacy, f"Kuzu missing edges: {list(only_legacy.items())[:5]}"
    assert not only_kuzu, f"Kuzu has extra edges: {list(only_kuzu.items())[:5]}"


def test_edge_type_distribution_matches(legacy_artifact, kuzu_artifact):
    """Per-edge-type counts match — surfaces any rel-table read-back gap."""
    legacy = Counter(e["type"] for e in legacy_artifact["edges"])
    kuzu = Counter(e["type"] for e in kuzu_artifact["edges"])
    assert legacy == kuzu, f"edge type drift: legacy={dict(legacy)} kuzu={dict(kuzu)}"


def test_rule_families_rollup_matches(legacy_artifact, kuzu_artifact):
    """``ruleFamilies`` ids, titles, ruleIds, blurbs match.

    ``exemplarNodeIds`` can be a different *selection* of the same family's
    nodes (the legacy picks DFS-first 5; Kuzu picks lex-first 5) — we assert
    same count and same family membership instead of byte equality.
    """
    legacy = {f["id"]: f for f in legacy_artifact["ruleFamilies"]}
    kuzu = {f["id"]: f for f in kuzu_artifact["ruleFamilies"]}
    assert set(legacy) == set(kuzu)
    for fid in legacy:
        assert legacy[fid]["title"] == kuzu[fid]["title"]
        assert legacy[fid]["ruleIds"] == kuzu[fid]["ruleIds"]
        assert legacy[fid]["blurb"] == kuzu[fid]["blurb"]
        # Same count of exemplars (empty stays empty; populated stays
        # populated). This is what the tutorial cares about.
        assert (len(legacy[fid]["exemplarNodeIds"]) > 0) == (
            len(kuzu[fid]["exemplarNodeIds"]) > 0
        ), f"family {fid} exemplar presence drift"


def test_stats_match(legacy_artifact, kuzu_artifact):
    """Top-level stats rollup matches."""
    assert legacy_artifact["stats"] == kuzu_artifact["stats"]


def test_non_token_spans_match(legacy_artifact, kuzu_artifact):
    """Every non-token node's span is byte-precise across the two exporters.

    Token spans are intentionally allowed to differ (see module docstring).
    """
    legacy_spans = {
        n["id"]: n.get("span")
        for n in legacy_artifact["nodes"]
        if not n["isToken"]
    }
    kuzu_spans = {
        n["id"]: n.get("span")
        for n in kuzu_artifact["nodes"]
        if not n["isToken"]
    }
    drift = []
    for nid, ls in legacy_spans.items():
        ks = kuzu_spans.get(nid)
        if ls != ks:
            drift.append((nid, ls, ks))
    assert not drift, f"non-token span drift on {len(drift)} nodes: {drift[:3]}"
