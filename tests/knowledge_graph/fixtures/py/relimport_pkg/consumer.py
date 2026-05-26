"""Consumer module — uses ``from .sibling import foo`` to bind ``foo``
and captures it in a lambda (v1.10-#2).

PyImport canonical for ``from .sibling import foo`` keeps the leading
dot (``.sibling.foo``) per v1.8-#1 walker convention. The connector
must resolve that against the consuming module's package path:
consumer's qualname (file stem ``consumer``) stripped of 1 segment
yields an empty package; appending ``sibling`` gives the absolute
qualname ``sibling`` which IS the corpus PyModule.name.
"""

from __future__ import annotations

from .sibling import foo


call_foo = lambda x: foo(x)  # noqa: E731
