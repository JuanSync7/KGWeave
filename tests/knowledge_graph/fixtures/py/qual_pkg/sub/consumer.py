"""Consumer module for v1.11-#3 multi-segment relative-import resolution.

``qual_pkg.sub.consumer`` does ``from .mod import foo`` (1-dot, single
segment) — but the consuming module's qualname is now 3 segments deep
(``qual_pkg.sub.consumer``) thanks to v1.11-#1. The resolver must
produce the absolute qualname ``qual_pkg.sub.mod`` and the lambda
capture of ``foo`` must classify as ``cross-file-import`` with
``origin_module == "qual_pkg.sub.mod"``.

A second binding tests the 2-dot escape: ``from ..mod import foo as
top_foo`` resolves up one package level, landing on
``qual_pkg.mod`` (the top-level mod.py sibling of ``sub/``).
"""

from __future__ import annotations

from .mod import foo
from ..mod import foo as top_foo


call_foo = lambda x: foo(x)  # noqa: E731
call_top_foo = lambda x: top_foo(x)  # noqa: E731
