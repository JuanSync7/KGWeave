"""Fixture: try/except ImportError fallback import.

`json` is a regular runtime import; `ujson` is wrapped in try/except
ImportError -- import_guard='try-import'.
"""
from __future__ import annotations

import json

try:
    import ujson
except ImportError:
    ujson = None  # type: ignore[assignment]


def dump(obj: object) -> str:
    return (ujson or json).dumps(obj)
