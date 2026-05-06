"""Common fixtures for KGWeave tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Make `kgweave` importable when running tests from the KGWeave repo root
# without an installed package (TDD mode).
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
