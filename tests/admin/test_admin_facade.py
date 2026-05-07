"""Tests for the kgweave.admin facade."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kgweave.admin import get_admin_backend
from kgweave.admin.facade import try_get_admin_backend


def test_get_admin_backend_returns_singleton():
    sentinel = MagicMock(name="GraphBackend")
    with patch(
        "kgweave.knowledge_graph.get_graph_backend", return_value=sentinel
    ):
        assert get_admin_backend() is sentinel


def test_try_get_admin_backend_swallows_failure():
    with patch(
        "kgweave.knowledge_graph.get_graph_backend",
        side_effect=RuntimeError("offline"),
    ):
        assert try_get_admin_backend() is None
