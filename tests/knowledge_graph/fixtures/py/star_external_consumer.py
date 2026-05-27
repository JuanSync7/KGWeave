"""Consumer of out-of-corpus star-import (v1.13-#3 fixture).

The star-import's origin module ``external_not_in_corpus`` is NOT shipped
as a corpus fixture. The connector must therefore (a) leave captures of
``some_external_name`` ``unresolved``, (b) emit NO ``cross-file-import``
row for them, and (c) still preserve the ``PyImport`` row with
``is_star=True`` pointing at ``external_not_in_corpus``.
"""

from __future__ import annotations

from external_not_in_corpus import *  # noqa: F401,F403


capture = lambda: some_external_name  # noqa: E731,F405
