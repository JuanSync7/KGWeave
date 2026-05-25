"""Negative-test fixture for v1.9-#3.

Imports ``json.loads`` — ``json`` is not part of the corpus we feed to
the connector, so the capture must stay ``unresolved`` (NOT
``cross-file-import``). Builtins are still recognised, so we use a
non-builtin imported name and assert it stays unresolved when the
origin module isn't in the corpus.
"""

from __future__ import annotations

from external_pkg_not_in_corpus import bar  # noqa: F401


call_bar = lambda x: bar(x)  # noqa: E731
