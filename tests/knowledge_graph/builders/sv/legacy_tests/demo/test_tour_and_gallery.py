"""SA5 acceptance: guided tour + use-case gallery contract.

The tour (``demo/data/tour.json``) and gallery (``demo/data/gallery.json``)
are static JSON registries consumed by ``demo/web/tour.js`` and
``demo/web/gallery.js``. This test pins the contract:

  - tour.json has >= 12 steps, covers all 10 rule families.
  - gallery.json has exactly 10 family cards, each with >=1 example.
  - Every ``run.canned`` query id in tour/gallery resolves in queries.json.
  - Every freeform DSL example parses cleanly via the Python port.
  - Every ``file`` id referenced exists in graph.json.files.
  - Every gallery family appears in the tour (and vice versa).

If you add a new tour step or gallery card, edit the JSON only — the test
will pick up the new entry automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

EXPERIMENT = Path(__file__).resolve().parents[2]
DATA = EXPERIMENT / "demo" / "data"
WEB = EXPERIMENT / "demo" / "web"
TOUR_JSON = DATA / "tour.json"
GALLERY_JSON = DATA / "gallery.json"
QUERIES_JSON = DATA / "queries.json"
GRAPH_JSON = DATA / "graph.json"
TOUR_JS = WEB / "tour.js"
GALLERY_JS = WEB / "gallery.js"


# ---------------------------------------------------------------------------
# Tiny port of query.js parseFreeform — keeps the test self-contained.
# ---------------------------------------------------------------------------


def _parse_freeform(query_str: str) -> dict:
    out: dict = {"filters": {}, "from": None, "via": None, "depth": 1, "direction": "fwd"}
    if not query_str or not query_str.strip():
        return {"error": "empty query"}
    for tok in query_str.strip().split():
        if "=" not in tok:
            return {"error": f"bad token: {tok!r}"}
        k, v = tok.split("=", 1)
        if k == "from":
            out["from"] = v
        elif k == "via":
            out["via"] = [t for t in v.split(",") if t]
        elif k == "depth":
            try:
                out["depth"] = int(v)
            except ValueError:
                return {"error": f"depth not int: {v!r}"}
        elif k == "direction":
            if v not in ("fwd", "rev"):
                return {"error": f"direction must be fwd|rev: {v!r}"}
            out["direction"] = v
        elif k in ("role", "name", "path", "file", "kind", "id"):
            out["filters"][k] = v
        else:
            return {"error": f"unknown key: {k!r}"}
    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tour():
    return json.loads(TOUR_JSON.read_text())


@pytest.fixture(scope="module")
def gallery():
    return json.loads(GALLERY_JSON.read_text())


@pytest.fixture(scope="module")
def queries():
    return json.loads(QUERIES_JSON.read_text())


@pytest.fixture(scope="module")
def queries_by_id(queries):
    return {q["id"]: q for q in queries["queries"]}


@pytest.fixture(scope="module")
def graph():
    return json.loads(GRAPH_JSON.read_text())


@pytest.fixture(scope="module")
def file_ids(graph):
    return {f["id"] for f in graph["files"]}


@pytest.fixture(scope="module")
def node_ids(graph):
    return {n["id"] for n in graph["nodes"]}


# ---------------------------------------------------------------------------
# Existence / shape
# ---------------------------------------------------------------------------


def test_tour_json_exists():
    """tour.json must be on disk."""
    assert TOUR_JSON.is_file()


def test_gallery_json_exists():
    """gallery.json must be on disk."""
    assert GALLERY_JSON.is_file()


def test_tour_js_exists():
    """tour.js module ships next to app.js."""
    assert TOUR_JS.is_file()


def test_gallery_js_exists():
    """gallery.js module ships next to app.js."""
    assert GALLERY_JS.is_file()


def test_tour_minimum_step_count(tour):
    """SA5 SPEC: tour has at least 12 steps (intro + 10 families + cookbook + BLOB)."""
    assert tour["version"] == "1"
    steps = tour["steps"]
    assert isinstance(steps, list)
    assert len(steps) >= 12, f"need >=12 steps, got {len(steps)}"


def test_gallery_has_ten_families(gallery):
    """SA5 SPEC: gallery has exactly 10 rule-family cards."""
    assert gallery["version"] == "1"
    families = gallery["families"]
    assert isinstance(families, list)
    assert len(families) == 10, f"need exactly 10 family cards, got {len(families)}"


def test_tour_step_shape(tour):
    """Each tour step has id, title, body; ids are unique."""
    seen = set()
    for s in tour["steps"]:
        for f in ("id", "title", "body"):
            assert f in s, f"step missing {f}: {s}"
        assert s["id"] not in seen, f"duplicate step id {s['id']}"
        seen.add(s["id"])


def test_gallery_card_shape(gallery):
    """Each gallery card has family, title, description, examples (>=1)."""
    seen = set()
    for c in gallery["families"]:
        for f in ("family", "title", "description", "examples"):
            assert f in c, f"card missing {f}: {c}"
        assert c["family"] not in seen
        seen.add(c["family"])
        assert isinstance(c["examples"], list)
        assert len(c["examples"]) >= 1, f"family {c['family']} has no examples"
        for ex in c["examples"]:
            assert "label" in ex
            # one of canned or freeform must be set
            assert ("canned" in ex) or ("freeform" in ex), (
                f"example needs canned|freeform: {ex}"
            )


# ---------------------------------------------------------------------------
# Cross-resolution: queries / files / nodes referenced must exist.
# ---------------------------------------------------------------------------


def _iter_run_specs(obj):
    """Yield every dict that looks like a run-spec (canned/freeform/file/node)."""
    if isinstance(obj, dict):
        # heuristic: dicts that have one of these keys are run-specs
        if any(k in obj for k in ("canned", "freeform", "file", "node")):
            yield obj
        for v in obj.values():
            yield from _iter_run_specs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_run_specs(v)


def test_tour_canned_queries_resolve(tour, queries_by_id):
    """Every step.run.canned in tour.json maps to a real queries.json entry."""
    for spec in _iter_run_specs(tour):
        cid = spec.get("canned")
        if cid:
            assert cid in queries_by_id, f"unknown canned query id: {cid}"


def test_gallery_canned_queries_resolve(gallery, queries_by_id):
    """Every example.canned in gallery.json maps to a real queries.json entry."""
    for spec in _iter_run_specs(gallery):
        cid = spec.get("canned")
        if cid:
            assert cid in queries_by_id, f"unknown canned query id: {cid}"


def test_tour_files_exist(tour, file_ids):
    """Every file id referenced by a tour step is in graph.json.files."""
    for spec in _iter_run_specs(tour):
        f = spec.get("file")
        if f:
            assert f in file_ids, f"unknown file id in tour: {f}"


def test_gallery_files_exist(gallery, file_ids):
    """Every file id referenced by a gallery example is in graph.json.files."""
    for spec in _iter_run_specs(gallery):
        f = spec.get("file")
        if f:
            assert f in file_ids, f"unknown file id in gallery: {f}"


def test_tour_node_anchors_exist(tour, node_ids):
    """Any step that references a specific node id must resolve in graph.json.nodes."""
    for spec in _iter_run_specs(tour):
        nid = spec.get("node")
        if nid:
            assert nid in node_ids, f"unknown node id in tour: {nid}"


def test_freeform_examples_parse(tour, gallery):
    """Every freeform DSL string in tour/gallery parses without error."""
    for obj in (tour, gallery):
        for spec in _iter_run_specs(obj):
            ff = spec.get("freeform")
            if ff:
                parsed = _parse_freeform(ff)
                assert "error" not in parsed, (
                    f"freeform {ff!r} failed to parse: {parsed.get('error')}"
                )


# ---------------------------------------------------------------------------
# 10-family coverage: tour and gallery must agree on the same family set.
# ---------------------------------------------------------------------------


REQUIRED_FAMILIES = {
    "module_structure",
    "continuous_assign_dataflow",
    "procedural_blocks",
    "instances_connectivity",
    "assertions_sva",
    "covergroups",
    "classes_oop",
    "packages_programs",
    "checkers_externs",
    "types_clocking_interfaces",
}


def test_gallery_covers_required_families(gallery):
    """Gallery's family ids cover the 10 mandatory rule-family showcases."""
    fams = {c["family"] for c in gallery["families"]}
    missing = REQUIRED_FAMILIES - fams
    assert not missing, f"gallery missing required families: {missing}"


def test_tour_covers_required_families(tour):
    """Every required family appears as a step.family on at least one tour step."""
    fams = {s.get("family") for s in tour["steps"] if s.get("family")}
    missing = REQUIRED_FAMILIES - fams
    assert not missing, f"tour missing required families: {missing}"


def test_tour_has_blob_step(tour):
    """The tour includes a dedicated 'What is BLOB?' step (id contains 'blob')."""
    ids = {s["id"] for s in tour["steps"]}
    assert any("blob" in i.lower() for i in ids), (
        f"tour must include a BLOB explainer step; ids: {ids}"
    )


def test_tour_has_cookbook_step(tour):
    """The tour ends with a query-cookbook step."""
    ids = [s["id"] for s in tour["steps"]]
    assert any("cookbook" in i.lower() for i in ids), (
        f"tour must include a cookbook step; ids: {ids}"
    )


# ---------------------------------------------------------------------------
# JS sanity — node --check if available.
# ---------------------------------------------------------------------------


def test_tour_js_node_check():
    """`node --check tour.js` succeeds, if Node is available."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available for --check")
    res = subprocess.run([node, "--check", str(TOUR_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check tour.js failed:\n{res.stderr}"


def test_gallery_js_node_check():
    """`node --check gallery.js` succeeds, if Node is available."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available for --check")
    res = subprocess.run([node, "--check", str(GALLERY_JS)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check gallery.js failed:\n{res.stderr}"


def test_tour_js_exports_required_symbols():
    """tour.js exports startTour / nextStep / prevStep / endTour / restartTour."""
    src = TOUR_JS.read_text()
    for sym in ("startTour", "nextStep", "prevStep", "endTour", "restartTour"):
        assert sym in src, f"tour.js missing exported symbol {sym}"


def test_gallery_js_exports_required_symbols():
    """gallery.js exports renderGallery."""
    src = GALLERY_JS.read_text()
    assert "renderGallery" in src, "gallery.js missing exported symbol renderGallery"


# ---------------------------------------------------------------------------
# Bespoke queries SA5 added — pin their expected counts so the contract is
# audit-able the same way SA4's q1..q7 are.
# ---------------------------------------------------------------------------


def _filter_count(graph: dict, flt: dict) -> int:
    n = 0
    for node in graph["nodes"]:
        sem = node.get("semantic") or {}
        ok = True
        for k, v in flt.items():
            if k == "role_in":
                if sem.get("role") not in v:
                    ok = False
                    break
            elif sem.get(k) != v:
                ok = False
                break
        if ok:
            n += 1
    return n


def test_q8_all_ports_count(graph, queries_by_id):
    """q8_all_ports: role=port returns 97 ports across the corpus."""
    assert "q8_all_ports" in queries_by_id
    n = _filter_count(graph, {"role": "port"})
    assert n == 97, f"expected 97 ports, got {n}"


def test_q9_all_covergroups_count(graph, queries_by_id):
    """q9_all_covergroups: covergroup+coverpoint+cross+coverage_bins rows."""
    assert "q9_all_covergroups" in queries_by_id
    n = _filter_count(
        graph,
        {"role_in": ["covergroup", "coverpoint", "cross", "coverage_bins"]},
    )
    # 2 cg + 4 cp + 1 cross + 3 bins = 10
    assert n == 10, f"expected 10 covergroup-family nodes, got {n}"


def test_q10_checkers_externs_count(graph, queries_by_id):
    """q10_checkers_externs: checker + checker_instance + extern_decl + extern_udp."""
    assert "q10_checkers_externs" in queries_by_id
    n = _filter_count(
        graph,
        {"role_in": ["checker", "checker_instance", "extern_decl", "extern_udp"]},
    )
    # 1 checker + 2 checker_instance + 3 extern_decl + 2 extern_udp = 8
    assert n == 8, f"expected 8 checker/extern nodes, got {n}"


def test_q11_packages_types_interfaces_count(graph, queries_by_id):
    """q11_packages_types_interfaces: package/typedef/interface/clocking/modport rows."""
    assert "q11_packages_types_interfaces" in queries_by_id
    n = _filter_count(
        graph,
        {"role_in": [
            "package", "typedef", "typedef_forward",
            "interface", "interface_port", "clocking", "clocking_item", "modport",
        ]},
    )
    # 2 + 3 + 6 + 3 + 3 + 3 + 4 + 3 = 27
    assert n == 27, f"expected 27 package/type/interface nodes, got {n}"


def test_q12_nets_vars_count(graph, queries_by_id):
    """q12_nets_vars: net + net_decl + nettype + user_defined_net_decl."""
    assert "q12_nets_vars" in queries_by_id
    n = _filter_count(
        graph,
        {"role_in": ["net", "net_decl", "nettype", "user_defined_net_decl"]},
    )
    # 56 + 6 + 3 + 2 = 67
    assert n == 67, f"expected 67 net-family nodes, got {n}"
