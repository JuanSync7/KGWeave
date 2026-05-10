"""TDD test for OPENTITAN_PROFILE constant in common/types.py (iter-003).

These tests must FAIL before the constant is added (ImportError on the
constant name), and PASS after it is introduced.
"""

from __future__ import annotations

import pytest

from kgweave.knowledge_graph.common.types import OPENTITAN_PROFILE, ProjectConventions


def test_opentitan_profile_constant_is_string():
    """OPENTITAN_PROFILE is a non-empty string."""
    assert isinstance(OPENTITAN_PROFILE, str)
    assert OPENTITAN_PROFILE  # non-empty


def test_opentitan_profile_constant_matches_classmethod_profile():
    """ProjectConventions.opentitan().profile equals the constant — not a raw literal."""
    pc = ProjectConventions.opentitan()
    assert pc.profile == OPENTITAN_PROFILE


def test_generic_profile_is_not_opentitan():
    """A bare ProjectConventions() profile is None, which is != OPENTITAN_PROFILE."""
    pc = ProjectConventions()
    assert pc.profile is None
    assert pc.profile != OPENTITAN_PROFILE


def test_opentitan_profile_constant_value():
    """Value is 'opentitan' — the canonical profile string."""
    assert OPENTITAN_PROFILE == "opentitan"
