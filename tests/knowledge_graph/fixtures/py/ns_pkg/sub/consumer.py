"""Consumer module for v1.12-#2 PEP 420 namespace-package qualname fixture.

``ns_pkg/sub/consumer.py`` does ``from .mod import foo`` — but neither
``ns_pkg/`` nor ``ns_pkg/sub/`` carries an ``__init__.py``. v1.12-#2's
qualname-walk widening must still produce ``ns_pkg.sub.consumer`` as
the consumer's qualname AND resolve the relative-import to
``ns_pkg.sub.mod``.
"""

from __future__ import annotations

from .mod import foo


call_foo = lambda x: foo(x)  # noqa: E731
