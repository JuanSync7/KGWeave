"""Star-import inside ``try / except ImportError`` (v1.12-#3).

The ``from star_target import *`` lives under a try-import idiom — walker
must mark BOTH ``is_star=True`` AND ``import_guard='try-import'``. The
connector must then NOT expand the star, so capturing ``foo`` in the
lambda must classify as ``unresolved`` (NOT ``cross-file-import``).
"""

from __future__ import annotations

try:
    from star_target import *  # noqa: F401,F403
except ImportError:
    pass


call_foo = lambda x: foo(x)  # noqa: E731,F405
