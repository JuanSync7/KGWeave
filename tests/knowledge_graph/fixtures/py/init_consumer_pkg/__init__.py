"""Package __init__.py that consumes its sibling module via ``from .
import sibling`` and captures the sibling module name inside a lambda
(v1.13-#1 fixture).

This pins the ``__init__.py``-aware contract of
``_resolve_relative_qualname``: a relative import with K=1 dots inside
``pkg/__init__.py`` should resolve to ``pkg.sibling`` — NOT ``sibling``
— because the consuming module's qualname IS ``pkg`` (the package
itself), not a leaf inside ``pkg``.
"""

from __future__ import annotations

from . import sibling


call_sibling_foo = lambda x: sibling.foo(x)  # noqa: E731
