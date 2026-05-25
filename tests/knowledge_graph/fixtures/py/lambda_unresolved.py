"""Lambda referencing a name not bound anywhere in the file (v1.8-#3).

``mystery`` is neither bound nor a builtin (after construction the
import wouldn't appear here — the binding genuinely doesn't exist in
this file). Expected resolution: ``mystery`` -> ``unresolved``.
"""

from __future__ import annotations


bad = lambda x: mystery(x)  # noqa: E731, F821
