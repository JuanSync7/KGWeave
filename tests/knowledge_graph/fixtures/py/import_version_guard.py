"""Fixture: import guarded by ``sys.version_info`` check.

`sys` is a plain runtime import; `tomllib` is conditional on Python
3.11+ -- import_guard='version-guard'.
"""
from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import tomllib
