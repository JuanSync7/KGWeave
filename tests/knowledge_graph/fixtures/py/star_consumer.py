"""Star-import consumer fixture (v1.10-#3).

Does ``from star_target import *`` and captures ``foo`` (public, should
lift to ``cross-file-import``) and ``_private`` (filtered, must stay
``unresolved``) inside lambdas.
"""

from __future__ import annotations

from star_target import *  # noqa: F401,F403


call_foo = lambda x: foo(x)  # noqa: E731,F405
call_private = lambda x: _private(x)  # noqa: E731,F405
