"""v1.13-#4 fixture: namespace-package nested-subpackage walker.

No ``__init__.py`` anywhere in ``ns_nested/``. ``mod.py`` lives in
``ns_nested/sub/`` (mixed: has both ``.py`` and a subdir ``inner/``)
and must qualify to ``ns_nested.sub.mod``.
"""

value = 1
