"""Star-import consumer for ``star_target_all`` (v1.10-#3).

``from star_target_all import *`` honours the target's ``__all__``:
capturing ``bar`` should lift to ``cross-file-import``; capturing
``baz`` (not in ``__all__``) must stay ``unresolved``.
"""

from __future__ import annotations

from star_target_all import *  # noqa: F401,F403


call_bar = lambda x: bar(x)  # noqa: E731,F405
call_baz = lambda x: baz(x)  # noqa: E731,F405
