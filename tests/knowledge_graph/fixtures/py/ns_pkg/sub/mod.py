"""Leaf module for v1.12-#2 PEP 420 namespace-package qualname fixture.

No ``__init__.py`` exists in ``ns_pkg/`` or ``ns_pkg/sub/`` — this is a
PEP 420 namespace package. Walker must still report
``PyModule.name == 'ns_pkg.sub.mod'``.
"""

from __future__ import annotations


def foo(x):
    return x
