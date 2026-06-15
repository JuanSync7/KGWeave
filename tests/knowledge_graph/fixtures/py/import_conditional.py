"""Fixture: import inside a plain ``if <flag>:`` block.

`os` is a regular runtime import; `optional_dep` is conditional on a
runtime flag -- import_guard='conditional'.
"""
from __future__ import annotations

import os

SOME_FLAG = bool(os.environ.get("ENABLE_OPTIONAL"))

if SOME_FLAG:
    import optional_dep
