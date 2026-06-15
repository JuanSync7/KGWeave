"""PyComprehension free-name capture fixture for v1.9-#1.

Single comprehension inside ``outer()`` referencing four kinds of
captures so the scope-resolution connector exercises all four
classifications in one pass:

* ``y``       -> local in enclosing function scope ``outer``
                  (``local-in-enclosing``)
* ``OFFSET``  -> module-level binding
                  (``module-level``)
* ``len``     -> builtin
                  (``builtin``)
* ``mystery`` -> not bound anywhere in this file
                  (``unresolved``)

The comprehension's own iter-target ``x`` MUST NOT appear in the
captures list (it's locally bound by ``for x in ...``).
"""

from __future__ import annotations


OFFSET = 10


def outer() -> list[int]:
    y = 1
    return [
        x + y + OFFSET + len(str(mystery))  # noqa: F821
        for x in range(3)
    ]
