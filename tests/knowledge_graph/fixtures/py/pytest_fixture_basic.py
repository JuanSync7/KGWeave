"""Fixture: a function decorated with ``@pytest.fixture``.

Used by v1.7-#4 decorator-aware connector tests. The connector must
promote ``PyFunction.payload.semantic_role`` to ``"fixture"`` when a
decorator's outer name resolves to ``pytest.fixture``.

Both bare ``@pytest.fixture`` and parametrised ``@pytest.fixture(...)``
must promote.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def simple_fixture() -> int:
    return 1


@pytest.fixture(scope="module")
def parametrised_fixture() -> int:
    return 2
