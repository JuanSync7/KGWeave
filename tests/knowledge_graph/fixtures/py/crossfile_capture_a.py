"""Module A for v1.9-#3 cross-file capture resolution fixture.

Defines ``foo`` and ``Widget`` at module level. Module B imports them
and references them inside a lambda; the connector should classify
those captures as ``cross-file-import`` with
``origin_module == "crossfile_capture_a"``.
"""

from __future__ import annotations


def foo(x):
    return x


class Widget:
    pass
