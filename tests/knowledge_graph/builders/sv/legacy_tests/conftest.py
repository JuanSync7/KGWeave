"""Make scripts/ importable as `scripts.<module>` for the round-trip tests."""

from __future__ import annotations

import sys
from pathlib import Path

_EXPERIMENT_DIR = Path(__file__).resolve().parent.parent
if str(_EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_EXPERIMENT_DIR))
# Repo root — needed so `knowledge_graph.builders.sv.semantic` imports resolve
# once the migration introduces the new package.
_REPO_ROOT = _EXPERIMENT_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
