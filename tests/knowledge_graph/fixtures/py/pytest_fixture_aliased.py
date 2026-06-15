"""Fixture: pytest imported under an alias used as decorator base.

Used by v1.8-#1 alias-aware decorator-semantics connector tests. The
connector must resolve ``pt.fixture`` -> ``pytest.fixture`` via the
per-file import-rename map and promote ``aliased_fixture`` to
``semantic_role="fixture"``.
"""
from __future__ import annotations

import pytest as pt


@pt.fixture
def aliased_fixture():
    return 42
