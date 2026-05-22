"""Both demo exporters must surface a ``gc_pruned`` field in their stats dict.

v1.5-#6 (charter §6). The Kuzu-port exporter routes through
:func:`knowledge_graph.extract`, whose :class:`ExtractStats.gc_pruned` reports
the number of origins pruned by the GC pass. The legacy in-memory exporter has
no GC concept, but emits the same field as ``0`` for shape parity so downstream
consumers can read either artifact uniformly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXP_DIR = _REPO_ROOT / "research" / "ast_experiment"
_SCRIPTS_DIR = _EXP_DIR / "scripts"
_SRC_DIR = _REPO_ROOT / "src"
for _p in (str(_EXP_DIR), str(_REPO_ROOT), str(_SRC_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_FIXTURE_FILES = [
    _EXP_DIR / "corpus" / "fifo.sv",
    _EXP_DIR / "corpus" / "fifo_pkg.sv",
]


@pytest.mark.timeout(300)
def test_legacy_exporter_emits_gc_pruned(tmp_path):
    """Legacy in-memory exporter emits ``gc_pruned`` (always 0)."""
    from scripts.export_demo_graph import export as legacy_export

    art = legacy_export(_FIXTURE_FILES, tmp_path / "graph.json")
    assert "gc_pruned" in art["stats"], (
        "legacy exporter stats dict missing gc_pruned"
    )
    assert art["stats"]["gc_pruned"] == 0


@pytest.mark.timeout(300)
def test_kuzu_exporter_emits_gc_pruned(tmp_path):
    """Kuzu-port exporter emits ``gc_pruned`` sourced from ExtractStats."""
    from scripts.export_demo_graph_kuzu import export as kuzu_export

    art = kuzu_export(
        _FIXTURE_FILES,
        tmp_path / "graph.json",
        store_dir=tmp_path / "store",
        corpus="demo-stats-test",
    )
    assert "gc_pruned" in art["stats"], (
        "kuzu exporter stats dict missing gc_pruned"
    )
    # On a fresh store with no prior origins, gc_pruned is 0; what we assert
    # is that the field is wired through, not its value.
    assert isinstance(art["stats"]["gc_pruned"], int)
    assert art["stats"]["gc_pruned"] >= 0
