"""Package __init__.py that consumes a member of its sibling module via
``from .sibling import foo`` and captures ``foo`` inside a lambda
(v1.13-#1 fixture).

This pins the ``__init__.py``-aware contract of
``_resolve_relative_qualname``. The walker canonical for
``from .sibling import foo`` is ``.sibling.foo`` (K=1). Inside a
package ``__init__.py`` the consuming qualname is literally ``pkg``
(N=1), so the bare ``N - K`` rule retains 0 segments and resolves to
top-level ``sibling.foo`` — which misses because the corpus module is
``init_consumer_pkg.sibling``, not ``sibling``. v1.13-#1's
``is_init_module=True`` mode uses effective K' = K - 1, retaining 1
segment, and resolves to ``init_consumer_pkg.sibling.foo`` — the
correct cross-file target.
"""

from __future__ import annotations

from .sibling import foo


call_foo = lambda x: foo(x)  # noqa: E731
