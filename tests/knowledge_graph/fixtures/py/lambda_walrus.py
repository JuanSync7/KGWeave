"""Lambda capturing a walrus-bound name from the enclosing scope (v1.8-#3).

The walrus target ``cached`` is introduced inside ``host``'s body and
is therefore bound at function scope. The lambda's reference must
resolve to ``local-in-enclosing``.
"""

from __future__ import annotations


def host(seed):
    if (cached := seed * 2) > 0:
        return lambda x: x + cached
    return lambda x: x
