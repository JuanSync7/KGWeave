"""Goal 1: pytest basetemp defaults to ~/.pytest-tmp (not /tmp tmpfs).

Why this matters: the box has a 16 GB tmpfs on /tmp; Kuzu test DBs ~3 MB each
across 2500+ tests can exhaust it. Redirecting basetemp to root FS prevents
disk-full hangs.
"""
from __future__ import annotations

import os
from pathlib import Path


def test_basetemp_under_pytest_tmp_home(tmp_path: Path, request) -> None:
    """tmp_path should resolve under ~/.pytest-tmp, not /tmp."""
    expected_root = Path(os.path.expanduser("~/.pytest-tmp")).resolve()
    actual = tmp_path.resolve()
    assert str(actual).startswith(str(expected_root)), (
        f"tmp_path {actual} is not under {expected_root}; "
        f"basetemp config must be missing"
    )


def test_basetemp_factory_reports_home_root(tmp_path_factory) -> None:
    """tmp_path_factory.getbasetemp() should sit under ~/.pytest-tmp."""
    expected_root = Path(os.path.expanduser("~/.pytest-tmp")).resolve()
    basetemp = Path(tmp_path_factory.getbasetemp()).resolve()
    assert str(basetemp).startswith(str(expected_root)), (
        f"basetemp {basetemp} not under {expected_root}"
    )
