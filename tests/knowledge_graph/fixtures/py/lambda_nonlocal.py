"""Lambda capturing a name promoted via ``nonlocal`` (v1.8-#3).

``inner`` re-declares ``x`` as ``nonlocal``, binding it to the
``outer``-scoped ``x``. The returned lambda captures ``x`` which must
resolve to the enclosing scope, not be marked unresolved.

Expected resolution: ``x`` -> ``local-in-enclosing``.
"""

from __future__ import annotations


def outer():
    x = 1

    def inner():
        nonlocal x
        return lambda: x

    return inner
