"""Lambda using Python builtins (v1.8-#3).

The lambda references ``len`` and ``range``, neither of which is bound
in any enclosing scope. Expected resolution: both -> ``builtin``.
"""

from __future__ import annotations


use_builtins = lambda xs: len(list(range(len(xs))))  # noqa: E731
