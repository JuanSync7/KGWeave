"""Static validator for the SA3 demo FE skeleton.

Without a browser, we can still:
  - confirm all local href/src targets in index.html exist on disk;
  - confirm CDN URLs are well-formed esm.sh ESM imports;
  - confirm app.js fetches ../data/graph.json;
  - syntax-check app.js via `node --check` if node is available;
  - confirm key DOM containers + JS hooks line up (id="cy" used by app.js,
    "file-rail"/"code-pane"/"graph-pane"/"inspector" referenced in app.js).

This is intentionally written with stdlib only — it lives in scripts/, not in
src/semantic/, so the no-regex invariant does not apply here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parents[1]
WEB = EXPERIMENT / "demo" / "web"
DATA = EXPERIMENT / "demo" / "data"


def _fail(msg: str) -> None:
    print(f"VALIDATOR FAIL: {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"  ok: {msg}")


def main() -> int:
    print(f"validating {WEB}")
    for name in ("index.html", "style.css", "app.js", "query.js", "tour.js", "gallery.js"):
        f = WEB / name
        if not f.is_file():
            _fail(f"missing {f}")
        if f.stat().st_size == 0:
            _fail(f"empty {f}")
        _ok(f"{name} present ({f.stat().st_size} bytes)")

    graph = DATA / "graph.json"
    if not graph.is_file():
        _fail(f"missing {graph}")
    _ok(f"graph.json present ({graph.stat().st_size} bytes)")

    queries_json = DATA / "queries.json"
    if not queries_json.is_file():
        _fail(f"missing {queries_json}")
    _ok(f"queries.json present ({queries_json.stat().st_size} bytes)")

    tour_json = DATA / "tour.json"
    if not tour_json.is_file():
        _fail(f"missing {tour_json}")
    _ok(f"tour.json present ({tour_json.stat().st_size} bytes)")

    gallery_json = DATA / "gallery.json"
    if not gallery_json.is_file():
        _fail(f"missing {gallery_json}")
    _ok(f"gallery.json present ({gallery_json.stat().st_size} bytes)")

    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    # 1. Local refs in index.html
    refs = re.findall(r'(?:href|src)="([^"]+)"', html)
    for rel in refs:
        if rel.startswith(("http://", "https://", "//", "#", "data:", "mailto:")):
            continue
        tgt = (WEB / rel).resolve()
        if not tgt.exists():
            _fail(f"index.html references missing local asset: {rel}")
        _ok(f"local ref {rel} -> {tgt.name}")

    # 2. app.js loaded as module
    if not re.search(r'<script[^>]+type="module"[^>]+src="(?:\./)?app\.js"', html):
        _fail("index.html missing <script type=module src=app.js>")
    _ok("index.html loads app.js as ESM module")

    # 3. Required DOM containers
    for sel in ("file-rail", "code-pane", "graph-pane", "inspector", "cy"):
        if f'id="{sel}"' not in html:
            _fail(f'index.html missing id="{sel}"')
        if sel not in js:
            _fail(f'app.js does not reference container id "{sel}"')
        _ok(f'container "#{sel}" wired in HTML + JS')

    # 4. CDN imports well-formed
    cdn_patterns = [
        (r"https://esm\.sh/cytoscape@3\.\d+\.\d+", "cytoscape"),
        (r"https://esm\.sh/@codemirror/state@6\.\d+\.\d+", "@codemirror/state"),
        (r"https://esm\.sh/@codemirror/view@6\.\d+\.\d+", "@codemirror/view"),
    ]
    for pat, label in cdn_patterns:
        if not re.search(pat, js):
            _fail(f"app.js missing CDN import for {label} (pattern: {pat})")
        _ok(f"CDN import {label} pinned")

    # 5. graph.json fetch path
    if "../data/graph.json" not in js:
        _fail("app.js must fetch ../data/graph.json (relative)")
    _ok("graph.json fetched via relative path")

    # 6. Span fields used
    for field in ("startOffset", "endOffset", "span", "category"):
        if field not in js:
            _fail(f"app.js missing usage of {field}")
    _ok("span/category fields wired")

    # 7. No remote network calls beyond CDN ESM imports (CSP-friendly).
    bad = re.findall(r"\bfetch\(['\"]https?://[^'\"]+['\"]", js)
    if bad:
        _fail(f"app.js performs remote runtime fetch: {bad!r}")
    _ok("no runtime remote fetch() calls")

    # 8. node --check on app.js + query.js, if node available
    node = shutil.which("node")
    if node:
        for js_name in ("app.js", "query.js", "tour.js", "gallery.js"):
            res = subprocess.run([node, "--check", str(WEB / js_name)],
                                 capture_output=True, text=True)
            if res.returncode != 0:
                _fail(f"node --check {js_name} failed:\n{res.stderr}")
            _ok(f"node --check {js_name}: syntax OK")
    else:
        print("  skip: node not available for --check")

    # 9. SA4: query.js wired into app.js
    if "./query.js" not in js:
        _fail("app.js must import ./query.js")
    _ok("app.js imports query.js")
    # 10. Canned-query DOM hooks in index.html
    for sel in ("query-select", "query-freeform", "query-run", "query-clear",
                "results-list"):
        if f'id="{sel}"' not in html:
            _fail(f'index.html missing id="{sel}"')
        _ok(f'query panel "#{sel}" present')

    # 11. SA5: tour.js / gallery.js wired into app.js
    if "./tour.js" not in js:
        _fail("app.js must import ./tour.js")
    _ok("app.js imports tour.js")
    if "./gallery.js" not in js:
        _fail("app.js must import ./gallery.js")
    _ok("app.js imports gallery.js")

    # 12. SA5: toolbar buttons in index.html
    for sel in ("tour-start", "tour-restart", "cookbook-open", "gallery-open"):
        if f'id="{sel}"' not in html:
            _fail(f'index.html missing toolbar id="{sel}"')
        _ok(f'toolbar "#{sel}" present')

    # 13. SA5: tour.js exports the documented entry points
    tour_src = (WEB / "tour.js").read_text(encoding="utf-8")
    for sym in ("startTour", "nextStep", "prevStep", "endTour", "restartTour"):
        if sym not in tour_src:
            _fail(f"tour.js missing symbol {sym}")
    _ok("tour.js exports startTour/nextStep/prevStep/endTour/restartTour")

    # 14. SA5: gallery.js exports renderGallery
    gallery_src = (WEB / "gallery.js").read_text(encoding="utf-8")
    if "renderGallery" not in gallery_src:
        _fail("gallery.js missing symbol renderGallery")
    _ok("gallery.js exports renderGallery")

    print("VALIDATOR OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
