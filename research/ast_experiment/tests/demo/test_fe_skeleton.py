"""SA3 acceptance: validate the static FE skeleton wiring without a browser.

These tests check that:
  - index.html / style.css / app.js exist under demo/web/
  - index.html references local assets that resolve to real files
  - index.html references CDN ESM imports for Cytoscape + CodeMirror
  - app.js fetches ../data/graph.json (relative)
  - app.js implements the bidirectional flow: graph-click -> inspector +
    code-pane scroll/highlight; code-click handling; category color mapping;
    default token-hide and toggle controls
  - validate_demo_html.py script runs cleanly

We deliberately do not execute the JS — SA6 will add a Playwright end-to-end.
This file is the "red-then-green" gate for SA3.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

EXPERIMENT = Path(__file__).resolve().parents[2]
ROOT = EXPERIMENT.parents[1]
DEMO = EXPERIMENT / "demo"
WEB = DEMO / "web"
DATA = DEMO / "data"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_web_dir_exists():
    assert WEB.is_dir(), f"{WEB} should exist"


def test_required_files_present():
    for name in ("index.html", "style.css", "app.js"):
        f = WEB / name
        assert f.is_file() and f.stat().st_size > 0, f"missing {f}"


def test_graph_json_present():
    assert (DATA / "graph.json").is_file()


def test_index_html_local_references_resolve():
    html = _read(WEB / "index.html")
    for rel in re.findall(r'(?:href|src)="([^"]+)"', html):
        if rel.startswith(("http://", "https://", "//", "#", "mailto:")):
            continue
        if rel.startswith("data:"):
            continue
        target = (WEB / rel).resolve()
        assert target.exists(), f"unresolved local asset: {rel}"


def test_index_html_loads_app_js_as_module():
    html = _read(WEB / "index.html")
    assert re.search(
        r'<script[^>]+type="module"[^>]+src="(?:\./)?app\.js"', html
    ), "expected <script type=module src=app.js>"


def test_index_html_has_required_panes():
    html = _read(WEB / "index.html")
    for sel in ("file-rail", "code-pane", "graph-pane", "inspector"):
        assert sel in html, f"index.html missing #{sel} container"


def test_app_js_fetches_relative_graph_json():
    js = _read(WEB / "app.js")
    assert "../data/graph.json" in js, "app.js must fetch ../data/graph.json"


def test_app_js_imports_cytoscape_and_codemirror_from_cdn():
    js = _read(WEB / "app.js")
    assert re.search(r"https://esm\.sh/cytoscape@", js), "cytoscape ESM import missing"
    # CodeMirror 6 ships as @codemirror/state + view (+ language optional)
    assert re.search(r"https://esm\.sh/@codemirror/state@", js)
    assert re.search(r"https://esm\.sh/@codemirror/view@", js)


def test_app_js_has_category_color_mapping():
    js = _read(WEB / "app.js")
    for cat in ("semantic", "structural", "blob", "token"):
        assert cat in js, f"category color mapping missing for {cat}"


def test_app_js_has_edge_type_color_mapping():
    js = _read(WEB / "app.js")
    # spot-check a representative set
    for et in ("drives", "reads", "sensitive_to", "instantiates", "of_module"):
        assert et in js, f"edge type styling missing for {et}"


def test_app_js_implements_bidirectional_click_flow():
    js = _read(WEB / "app.js")
    # graph -> code: tap/click handler that uses span.file + startOffset/endOffset
    assert "startOffset" in js and "endOffset" in js
    assert "span" in js
    # inspector population
    assert "inspector" in js.lower()
    # CodeMirror dispatch (scroll + highlight)
    assert "EditorView" in js or "view.dispatch" in js or "dispatch(" in js


def test_app_js_default_hides_tokens_and_offers_toggle():
    js = _read(WEB / "app.js")
    # default-hide tokens; per-category toggle
    assert "hideTokens" in js or "hide-tokens" in js or "showTokens" in js
    # toggle UI (filters)
    assert "filter" in js.lower()


def test_validator_script_present_and_passes():
    script = EXPERIMENT / "scripts" / "validate_demo_html.py"
    assert script.is_file(), f"missing {script}"
    res = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        f"validator failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
