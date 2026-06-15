"""Star-import inside ``if TYPE_CHECKING:`` (v1.12-#3).

The ``from star_target import *`` lives under ``if TYPE_CHECKING:`` —
walker must mark BOTH ``is_star=True`` AND ``import_guard='type-checking'``.
The connector must then NOT expand the star (guarded star-imports don't
contribute to runtime cross-file resolution), so capturing ``foo`` in the
lambda must classify as ``unresolved`` (NOT ``cross-file-import``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from star_target import *  # noqa: F401,F403


call_foo = lambda x: foo(x)  # noqa: E731,F405
