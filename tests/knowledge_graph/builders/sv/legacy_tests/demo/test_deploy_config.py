"""SA6 — structural sanity checks for the GH-Pages deploy + Playwright wiring.

These tests are NOT a substitute for the actual Playwright E2E run; they
validate that:

* The Actions workflow YAML parses and references real files.
* The Playwright config webServer port + baseURL line up.
* Every spec file references DOM selectors that exist in the FE source.
* The demo README links the e2e README and the export script lives where
  the workflow expects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

_EXPERIMENT_DIR = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _EXPERIMENT_DIR.parent.parent
_DEMO_DIR = _EXPERIMENT_DIR / "demo"
_E2E_DIR = _DEMO_DIR / "e2e"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "demo-deploy.yml"
_INDEX_HTML = _DEMO_DIR / "web" / "index.html"
_APP_JS = _DEMO_DIR / "web" / "app.js"
_TOUR_JS = _DEMO_DIR / "web" / "tour.js"
_GALLERY_JS = _DEMO_DIR / "web" / "gallery.js"


# --------------------------------------------------------------------------- #
# Workflow                                                                    #
# --------------------------------------------------------------------------- #


def test_workflow_yaml_exists_and_parses() -> None:
    assert _WORKFLOW.is_file(), f"missing {_WORKFLOW}"
    data = yaml.safe_load(_WORKFLOW.read_text())
    assert isinstance(data, dict)
    # PyYAML decodes the `on:` key as the Python boolean True (YAML 1.1
    # truthy collision). Accept either form.
    on_key = "on" if "on" in data else True
    assert on_key in data, "workflow must declare an `on` trigger"
    assert "jobs" in data
    assert "build-test-deploy" in data["jobs"]


def test_workflow_references_real_paths() -> None:
    text = _WORKFLOW.read_text()
    assert "research/ast_experiment/tests/" in text
    assert "research/ast_experiment/scripts/export_demo_graph.py" in text
    assert "research/ast_experiment/scripts/validate_demo_html.py" in text
    assert "research/ast_experiment/demo/e2e" in text
    # Ensure the publish dir wiring stages the demo under sv-ast-demo/
    # (so KGWeave's Pages site can grow other sibling sections later).
    assert "_site/sv-ast-demo" in text
    assert "_site/sv-ast-demo/data" in text


def test_workflow_pins_action_versions() -> None:
    text = _WORKFLOW.read_text()
    for action in [
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/setup-node@v4",
        "actions/upload-artifact@v4",
        "peaceiris/actions-gh-pages@v3",
    ]:
        assert action in text, f"workflow must pin {action}"


def test_workflow_concurrency_and_permissions() -> None:
    data = yaml.safe_load(_WORKFLOW.read_text())
    assert "concurrency" in data
    assert "permissions" in data
    assert data["permissions"].get("contents") == "write"


# --------------------------------------------------------------------------- #
# Playwright config                                                           #
# --------------------------------------------------------------------------- #


def test_playwright_config_exists() -> None:
    cfg = _E2E_DIR / "playwright.config.ts"
    assert cfg.is_file(), f"missing {cfg}"


def test_playwright_baseurl_matches_webserver_port() -> None:
    cfg_text = (_E2E_DIR / "playwright.config.ts").read_text()
    # Constant PORT block — `const PORT = NNNN;`
    assert "const PORT = 8765;" in cfg_text
    assert "http://${HOST}:${PORT}/web/" in cfg_text
    assert "python3 -m http.server ${PORT}" in cfg_text
    # webServer cwd = parent of e2e/, so http.server roots at demo/.
    assert 'cwd: ".."' in cfg_text


def test_e2e_package_json_lists_playwright() -> None:
    pkg = json.loads((_E2E_DIR / "package.json").read_text())
    deps = pkg.get("devDependencies", {})
    assert "@playwright/test" in deps
    assert "playwright" in deps


# --------------------------------------------------------------------------- #
# Specs reference real DOM hooks                                              #
# --------------------------------------------------------------------------- #


_REQUIRED_SPECS = [
    "page-load.spec.ts",
    "graph-code-link.spec.ts",
    "query.spec.ts",
    "tour.spec.ts",
    "gallery.spec.ts",
    "filters.spec.ts",
]


@pytest.mark.parametrize("spec_name", _REQUIRED_SPECS)
def test_spec_file_exists(spec_name: str) -> None:
    assert (_E2E_DIR / "tests" / spec_name).is_file(), f"missing spec {spec_name}"


def test_specs_clear_localstorage_in_beforeeach() -> None:
    # SA5 documented that kgweave.tour.step persists across tests; every
    # spec must wipe it in beforeEach to avoid cross-test bleed.
    for name in _REQUIRED_SPECS:
        text = (_E2E_DIR / "tests" / name).read_text()
        assert "localStorage.clear" in text, f"{name} must clear localStorage"


def test_specs_reference_real_selectors() -> None:
    """Every #id selector used by a spec must appear in index.html or a JS
    module that creates it dynamically (tour overlay, gallery overlay)."""
    html = _INDEX_HTML.read_text()
    app = _APP_JS.read_text()
    tour = _TOUR_JS.read_text()
    gallery = _GALLERY_JS.read_text()
    haystack = html + "\n" + app + "\n" + tour + "\n" + gallery

    required_ids = [
        "#stats",
        "#cy",
        "#code-pane",
        "#file-rail",
        "#query-select",
        "#query-freeform",
        "#query-run",
        "#query-clear",
        "#results-list",
        "#results-summary",
        "#tour-start",
        "#tour-restart",
        "#tour-overlay",
        "#gallery-open",
        "#gallery-overlay",
        "#inspector",
    ]
    # The `#foo` selector form lives in HTML as `id="foo"` and in JS as
    # either `getElementById("foo")` or `id = "foo"` template assignments.
    for sel in required_ids:
        bare = sel.lstrip("#")
        assert (
            sel in haystack
            or f'id="{bare}"' in haystack
            or f'"{bare}"' in haystack
        ), f"selector {sel} not wired anywhere in FE source"


def test_specs_reference_real_classes() -> None:
    """Class-based selectors used by tour/gallery specs must exist in the
    JS modules that create them."""
    tour = _TOUR_JS.read_text()
    gallery = _GALLERY_JS.read_text()
    # tour.js owns these CSS classes.
    for cls in [".tour-overlay", ".tour-card", ".tour-meta", ".tour-next",
                ".tour-prev", ".tour-skip"]:
        assert cls.lstrip(".") in tour, f"{cls} missing from tour.js"
    # gallery.js owns these.
    for cls in [".gallery-overlay", ".gallery-card", ".gallery-run"]:
        assert cls.lstrip(".") in gallery, f"{cls} missing from gallery.js"


def test_specs_reference_localstorage_key() -> None:
    tour_spec = (_E2E_DIR / "tests" / "tour.spec.ts").read_text()
    assert "kgweave.tour.step" in tour_spec
    # The same key must appear in tour.js (the SA5 contract).
    assert "kgweave.tour.step" in _TOUR_JS.read_text()


def test_specs_reference_canned_query_ids() -> None:
    """Specs that select from #query-select must use canned IDs that exist
    in queries.json."""
    queries = json.loads((_DEMO_DIR / "data" / "queries.json").read_text())
    canned_ids = {q["id"] for q in queries["queries"]}
    query_spec = (_E2E_DIR / "tests" / "query.spec.ts").read_text()
    glc_spec = (_E2E_DIR / "tests" / "graph-code-link.spec.ts").read_text()
    for ref in ["q1_all_modules", "q5_top_to_fifo_path"]:
        assert ref in canned_ids, f"queries.json missing {ref}"
        assert ref in (query_spec + glc_spec), f"no spec exercises {ref}"


# --------------------------------------------------------------------------- #
# Demo README + root README                                                   #
# --------------------------------------------------------------------------- #


def test_demo_readme_exists_and_documents_local_run() -> None:
    readme = _DEMO_DIR / "README.md"
    assert readme.is_file()
    text = readme.read_text()
    assert "python3 -m http.server" in text
    assert "export_demo_graph.py" in text
    assert "github.io" in text


def test_root_readme_links_demo() -> None:
    text = (_REPO_ROOT / "README.md").read_text()
    assert "research/ast_experiment/demo/README.md" in text
    assert "github.io" in text


def test_e2e_readme_documents_spec_suite() -> None:
    text = (_E2E_DIR / "README.md").read_text()
    for spec in _REQUIRED_SPECS:
        assert spec in text, f"{spec} not mentioned in e2e/README.md"
