"""Top-level package marker for v1.11-#1 qualname fixture.

``qual_pkg/`` contains a nested package ``sub/`` containing ``mod.py``.
The v1.11-#1 walker rule expects ``PyModule.name`` to be the
dot-joined package path: ``qual_pkg`` for this __init__, ``qual_pkg.sub``
for the nested __init__, and ``qual_pkg.sub.mod`` for the leaf module.
"""
