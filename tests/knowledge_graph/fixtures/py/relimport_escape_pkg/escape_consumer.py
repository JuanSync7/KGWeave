"""Negative fixture — relative target escapes above the package root.

Consuming module qualname (file stem) is a single segment
``escape_consumer``. ``from ..outside import foo`` has 2 leading dots,
which would strip 2 segments off the consuming module's qualname — but
only 1 segment exists. Resolver returns ``None`` and the capture stays
``unresolved``.
"""

from __future__ import annotations

from ..outside import foo  # noqa: F401  (intentionally escapes)


call_foo = lambda x: foo(x)  # noqa: E731
