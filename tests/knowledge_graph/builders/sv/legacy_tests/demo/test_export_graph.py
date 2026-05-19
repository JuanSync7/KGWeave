"""Tests for ``scripts/export_demo_graph.py`` — schema + span correctness.

These tests are the SA2 acceptance harness for the static GH-Pages demo
(SPEC.md §6). They run the exporter end-to-end against the full corpus,
load the emitted ``demo/data/graph.json``, and check the schema in
SPEC.md §3 verbatim plus the span correctness invariants.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
EXP_DIR = REPO_ROOT / "research" / "ast_experiment"
GRAPH_JSON = EXP_DIR / "demo" / "data" / "graph.json"
EXPORTER = EXP_DIR / "scripts" / "export_demo_graph.py"


ALLOWED_CATEGORIES = {"semantic", "structural", "blob", "token"}
ALLOWED_EDGE_VERSION = "1"

# SPEC.md §4 — the 10 family ids the tutorial drives.
EXPECTED_FAMILY_IDS = {
    "structure",
    "ports_params",
    "nets_vars",
    "continuous_assign_dataflow",
    "procedural_blocks",
    "instances_hierarchy",
    "assertions_clocking",
    "covergroups",
    "classes_constraints",
    "packages_types_externs",
}


@pytest.fixture(scope="module")
def graph_json():
    """Build the artifact once; load JSON; cache for every test in this module."""
    if not GRAPH_JSON.exists():
        # Build the artifact via the CLI to exercise the end-to-end path.
        subprocess.run(
            [sys.executable, str(EXPORTER)],
            check=True,
            cwd=str(REPO_ROOT),
        )
    return json.loads(GRAPH_JSON.read_text())


def test_graph_has_required_top_level_keys(graph_json):
    """Top-level JSON has version, files, nodes, edges, ruleFamilies, stats."""
    required = {"version", "generatedAt", "files", "nodes", "edges", "ruleFamilies", "stats"}
    assert required.issubset(graph_json.keys()), f"missing: {required - set(graph_json.keys())}"


def test_version_field_matches_spec(graph_json):
    """``version`` is the locked schema version ``"1"`` (SPEC §3.1)."""
    assert graph_json["version"] == ALLOWED_EDGE_VERSION


def test_files_array_inlines_source(graph_json):
    """Every FileEntry inlines its raw source bytes so the FE never re-fetches."""
    assert isinstance(graph_json["files"], list)
    assert len(graph_json["files"]) >= 10  # SPEC §1: 10 corpus files
    for f in graph_json["files"]:
        for k in ("id", "path", "source", "lineCount", "rootNodeId"):
            assert k in f, f"file entry missing {k}: {f.get('id')}"
        assert isinstance(f["source"], str)
        assert len(f["source"]) > 0
        assert f["lineCount"] >= 1


def test_every_node_has_required_fields(graph_json):
    """Schema-validate every NodeEntry — id, type, kind, isToken, category, payload."""
    nodes = graph_json["nodes"]
    assert len(nodes) > 0
    for n in nodes:
        for k in ("id", "type", "kind", "isToken", "category", "payload"):
            assert k in n, f"node {n.get('id')} missing {k}"
        assert isinstance(n["isToken"], bool)
        assert n["category"] in ALLOWED_CATEGORIES, f"bad category {n['category']} on {n['id']}"


def test_promoted_nodes_have_valid_category(graph_json):
    """Every node carrying a ``semantic`` dict has category ``"semantic"``."""
    for n in graph_json["nodes"]:
        if n.get("semantic"):
            assert n["category"] == "semantic", f"{n['id']} is queryable but category={n['category']}"


def test_non_token_spans_are_consistent_with_source(graph_json):
    """For every non-null span, ``source[startOffset:endOffset]`` is non-empty and slices the FileEntry."""
    files_by_id = {f["id"]: f for f in graph_json["files"]}
    checked = 0
    for n in graph_json["nodes"]:
        sp = n.get("span")
        if sp is None:
            continue
        assert sp["file"] in files_by_id, f"unknown file id {sp['file']}"
        src = files_by_id[sp["file"]]["source"]
        assert 0 <= sp["startOffset"] < sp["endOffset"] <= len(src), (
            f"bad offsets on {n['id']}: {sp}"
        )
        snippet = src[sp["startOffset"]:sp["endOffset"]]
        assert snippet, f"empty span on {n['id']}"
        assert sp["startLine"] >= 1
        assert sp["endLine"] >= sp["startLine"]
        checked += 1
    assert checked > 100, f"only {checked} spans checked — exporter likely emitted span:null too liberally"


def test_queryable_nodes_have_span_unless_synthetic(graph_json):
    """Every queryable node whose id is NOT a synthetic ``_unresolved.*`` /
    ``<role>:<path>`` placeholder carries a non-null span."""
    missing = []
    for n in graph_json["nodes"]:
        if not n.get("semantic"):
            continue
        nid = n["id"]
        # Synthetic semantic-only nodes (added by promote, no pyslang origin)
        # use the form ``role:hier.path`` (no ``:n0001.Cls`` segment). Lift ids
        # always contain ``:n`` and a class suffix.
        is_lift_id = (":n" in nid) and ("." in nid.split(":", 1)[1])
        if not is_lift_id:
            continue  # synthetic — span:null is OK
        if n.get("span") is None:
            missing.append(nid)
    assert not missing, f"queryable lift nodes missing spans: {missing[:5]} ..."


def test_every_edge_endpoints_exist(graph_json):
    """Every edge's src and dst are present in the nodes array."""
    ids = {n["id"] for n in graph_json["nodes"]}
    orphans = []
    for e in graph_json["edges"]:
        if e["src"] not in ids:
            orphans.append(("src", e))
        if e["dst"] not in ids and not e["dst"].startswith("_unresolved."):
            orphans.append(("dst", e))
    assert not orphans, f"{len(orphans)} edges have unknown endpoints: {orphans[:3]}"


def test_every_edge_has_span_from_source_node(graph_json):
    """Edge span equals the source node's span (SA1 decision §3.4) — or null if the source has none."""
    nodes_by_id = {n["id"]: n for n in graph_json["nodes"]}
    for e in graph_json["edges"]:
        src = nodes_by_id.get(e["src"])
        if src is None:
            continue
        assert e.get("span") == src.get("span"), (
            f"edge {e['id']} span mismatch with src {e['src']}"
        )


def test_rule_families_match_spec(graph_json):
    """The 10 family ids in SPEC §4 are all present, each with ruleIds + exemplarNodeIds."""
    fams = {f["id"]: f for f in graph_json["ruleFamilies"]}
    assert EXPECTED_FAMILY_IDS == set(fams.keys()), (
        f"family mismatch: got {set(fams.keys())}, want {EXPECTED_FAMILY_IDS}"
    )
    for fid, fam in fams.items():
        for k in ("id", "title", "ruleIds", "exemplarNodeIds", "blurb"):
            assert k in fam, f"family {fid} missing {k}"
        assert fam["ruleIds"], f"family {fid} has no rule ids"
        assert fam["exemplarNodeIds"], f"family {fid} has no exemplars — corpus didn't exercise it"


def test_stats_match_actual_counts(graph_json):
    """``stats`` rollup matches the array lengths."""
    s = graph_json["stats"]
    assert s["nodeCount"] == len(graph_json["nodes"])
    assert s["edgeCount"] == len(graph_json["edges"])
    sem_n = sum(1 for n in graph_json["nodes"] if n.get("semantic"))
    assert s["semanticNodeCount"] == sem_n


def test_edge_ids_are_unique(graph_json):
    """Edge ids are unique sequential strings (SPEC §3.4)."""
    ids = [e["id"] for e in graph_json["edges"]]
    assert len(ids) == len(set(ids))
