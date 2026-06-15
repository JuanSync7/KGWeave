"""Sibling module exporting ``foo`` for v1.13-#1 ``__init__.py``-consumer
fixture. The package ``__init__.py`` does ``from . import sibling`` and
captures the ``sibling`` module object inside a lambda; the connector
must classify that capture as ``module-import`` with
``origin_module == "init_consumer_pkg.sibling"``.
"""

from __future__ import annotations


def foo(x):
    return x


foo_value = 1
